// Temporary workload/ownership probe. NOT CDELS and NOT algorithm quality data.
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <array>
#include <atomic>
#include <cerrno>
#include <charconv>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <fcntl.h>
#include <memory>
#include <stdexcept>
#include <string>
#include <sys/syscall.h>
#include <unistd.h>
#include <vector>

namespace py = pybind11;
using Clock = std::chrono::steady_clock;
static uint64_t stamp() {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now().time_since_epoch()).count();
}
struct Counts { std::atomic<uint64_t> live_bytes{0}, active{0}; };

struct Result {
    const uint64_t seed, points, work;
    std::vector<uint64_t> history;
    uint64_t rng = 0, draws = 0, checksum = 0, scratch_checksum = 0, compute_ns = 0;
    std::shared_ptr<Counts> counts;
    Result(uint64_t s, uint64_t n, uint64_t w, size_t records, std::shared_ptr<Counts> c)
        : seed(s), points(n), work(w), history(records), counts(std::move(c)) {
        counts->live_bytes.fetch_add(history.size() * sizeof(uint64_t));
    }
    ~Result() { counts->live_bytes.fetch_sub(history.size() * sizeof(uint64_t)); }
    py::dict data() const {
        py::dict d;
        d["checksum"] = checksum; d["history"] = history; d["problem_points"] = points;
        d["rng_draws"] = draws; d["rng_state"] = rng; d["seed"] = seed;
        d["steps_per_record"] = work; d["workspace_checksum"] = scratch_checksum;
        return d;
    }
    static void number(std::string& out, uint64_t value) {
        char storage[32];
        const auto converted = std::to_chars(storage, storage + sizeof(storage), value);
        out.append(storage, converted.ptr);
    }
    std::string json() const {
        std::string out;
        out.reserve(history.size() * 22 + 256);
        out += "{\"checksum\":"; number(out, checksum);
        out += ",\"history\":[";
        for (size_t i = 0; i < history.size(); ++i) {
            if (i) out += ',';
            number(out, history[i]);
        }
        out += "],\"problem_points\":"; number(out, points);
        out += ",\"rng_draws\":"; number(out, draws);
        out += ",\"rng_state\":"; number(out, rng);
        out += ",\"seed\":"; number(out, seed);
        out += ",\"steps_per_record\":"; number(out, work);
        out += ",\"workspace_checksum\":"; number(out, scratch_checksum);
        out += "}\n";
        return out;
    }
};

class Bank {
    const size_t points_;
    const std::vector<uint64_t> matrix_;
    std::shared_ptr<Counts> counts_ = std::make_shared<Counts>();
    static std::vector<uint64_t> prepare(size_t n) {
        if (!n || n > 2000) throw std::invalid_argument("probe points must be 1..2000");
        std::vector<uint64_t> matrix(n * n);
        // Touch every page; allocated virtual size must not masquerade as RSS.
        for (size_t i = 0; i < matrix.size(); ++i) matrix[i] = (i * 7 + 13) % 100003;
        return matrix;
    }
public:
    explicit Bank(size_t points) : points_(points), matrix_(prepare(points)) {}
    std::unique_ptr<Result> run(uint64_t seed, size_t records, uint64_t work) {
        if (!records || records > 131072 || !work || work > 512)
            throw std::invalid_argument("probe workload out of range");
        const auto begin = stamp();
        counts_->active.fetch_add(1);
        auto result = std::make_unique<Result>(seed, points_, work, records, counts_);
        std::array<uint64_t, 1024> scratch{};
        uint64_t state = seed, value = 0, sum = 0;
        for (size_t i = 0; i < records; ++i) {
            for (uint64_t j = 0; j < work; ++j) {
                state = state * UINT64_C(6364136223846793005) + UINT64_C(1442695040888963407);
                const size_t slot = (state >> 32) % scratch.size();
                scratch[slot] += matrix_[state % matrix_.size()] ^ state;
                value = scratch[slot] ^ state;
            }
            result->history[i] = value;
            sum += value;
        }
        for (const auto x : scratch) result->scratch_checksum += x;
        result->rng = state; result->draws = records * work; result->checksum = sum;
        result->compute_ns = stamp() - begin;
        counts_->active.fetch_sub(1);
        return result;
    }
    py::dict diagnostics() const {
        py::dict d;
        d["problem_bytes"] = matrix_.size() * sizeof(uint64_t);
        d["live_history_bytes"] = counts_->live_bytes.load();
        d["active"] = counts_->active.load();
        d["bank_address"] = reinterpret_cast<uintptr_t>(this);
        d["matrix_address"] = reinterpret_cast<uintptr_t>(matrix_.data());
        d["native_tid"] = static_cast<uint64_t>(::syscall(SYS_gettid));
        return d;
    }
};

struct SaveTimes { uint64_t serialize_ns, write_ns, bytes; };
static SaveTimes save_native(const Result& result, const std::string& path) {
    const auto begin = stamp();
    const auto bytes = result.json();
    const auto serialized = stamp();
    const int fd = ::open(path.c_str(), O_WRONLY | O_CREAT | O_EXCL, 0600);
    if (fd < 0) throw std::runtime_error(std::strerror(errno));
    size_t offset = 0;
    while (offset < bytes.size()) {
        const ssize_t written = ::write(fd, bytes.data() + offset, bytes.size() - offset);
        if (written < 0 && errno == EINTR) continue;
        if (written <= 0) { ::close(fd); throw std::runtime_error("probe write failed"); }
        offset += static_cast<size_t>(written);
    }
    if (::fsync(fd)) { ::close(fd); throw std::runtime_error("probe fsync failed"); }
    if (::close(fd)) throw std::runtime_error("probe close failed");
    return SaveTimes{serialized - begin, stamp() - serialized, bytes.size()};
}

PYBIND11_MODULE(perf_kernel, m) {
    py::class_<Result>(m, "Result").def("to_dict", &Result::data)
        .def_readonly("compute_ns", &Result::compute_ns);
    py::class_<SaveTimes>(m, "SaveTimes").def_readonly("serialize_ns", &SaveTimes::serialize_ns)
        .def_readonly("write_ns", &SaveTimes::write_ns).def_readonly("bytes", &SaveTimes::bytes);
    py::class_<Bank>(m, "Bank").def(py::init<size_t>())
        .def("run", &Bank::run, py::call_guard<py::gil_scoped_release>())
        .def("diagnostics", &Bank::diagnostics);
    m.def("save_native", &save_native, py::call_guard<py::gil_scoped_release>());
}
