// Architecture gate 1 only. This is NOT CDELS or a production solver.
// Problem data is constructed once per Bank; each run owns all mutable state.
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <atomic>
#include <cerrno>
#include <chrono>
#include <cstdint>
#include <memory>
#include <stdexcept>
#include <string>
#include <sys/socket.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <utility>
#include <vector>

namespace py = pybind11;
using Ints = std::vector<int64_t>;
using Bits = std::vector<uint8_t>;

static uint64_t now_ns() {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
}

struct Problem {
    const std::string id;
    const Ints values;
    // Rows are items, columns are capacity dimensions, as in project MKP data.
    const std::vector<Ints> weights;
    const Ints capacities;

    Problem(std::string name, Ints v, std::vector<Ints> w, Ints c)
        : id(std::move(name)), values(std::move(v)), weights(std::move(w)),
          capacities(std::move(c)) {
        if (values.empty() || capacities.empty() || weights.size() != values.size())
            throw std::invalid_argument("invalid fixture dimensions");
        for (const auto& row : weights)
            if (row.size() != capacities.size())
                throw std::invalid_argument("invalid fixture weight row");
        for (const auto c0 : capacities)
            if (c0 < 0) throw std::invalid_argument("negative fixture capacity");
    }
};

struct Evaluation { int64_t fitness; bool feasible; Ints loads; };

static Evaluation evaluate(const Problem& p, const Bits& code) {
    Evaluation e{0, true, Ints(p.capacities.size(), 0)};
    for (size_t i = 0; i < code.size(); ++i) {
        if (code[i] > 1) throw std::logic_error("non-binary code");
        if (!code[i]) continue;
        e.fitness += p.values[i];
        for (size_t d = 0; d < e.loads.size(); ++d) e.loads[d] += p.weights[i][d];
    }
    for (size_t d = 0; d < e.loads.size(); ++d)
        if (e.loads[d] > p.capacities[d]) e.feasible = false;
    return e;
}

struct Random {
    uint32_t state;
    uint64_t draws = 0;
    explicit Random(uint32_t seed) : state(seed) {}
    uint32_t next() {
        state = state * UINT32_C(214013) + UINT32_C(2531011);
        ++draws;
        return (state >> 16u) & UINT32_C(0x7fff);
    }
};

struct Snapshot {
    uint64_t iteration;
    std::string label;
    Bits code;
    int64_t fitness;
    bool feasible;
    Ints loads;
    Bits best_code;
    int64_t best_fitness;
    uint32_t rng_state;
    uint64_t rng_draws;
    int64_t selected_item;
};

// These counters are diagnostic only, never used to choose a search operation.
struct Counters {
    std::atomic<uint64_t> active{0}, peak_active{0}, live_results{0};
    std::atomic<uint64_t> runs{0}, history_fitness_checks{0};
};

struct TaskScope {
    std::shared_ptr<Counters> counts;
    explicit TaskScope(std::shared_ptr<Counters> c) : counts(std::move(c)) {
        const auto active = counts->active.fetch_add(1) + 1;
        auto peak = counts->peak_active.load();
        while (peak < active && !counts->peak_active.compare_exchange_weak(peak, active)) {}
        counts->runs.fetch_add(1);
    }
    ~TaskScope() { counts->active.fetch_sub(1); }
};

struct Telemetry {
    uint64_t enter_ns = 0, compute_start_ns = 0, middle_ns = 0;
    uint64_t compute_finish_ns = 0, exit_ns = 0;
    uint64_t native_tid = 0, problem_address = 0, bank_address = 0;
};

// Optional synchronization for TESTS ONLY. The controller releases a phase only
// after every participant reaches it. No Python callback is used under nogil.
// This is NOT a proposed production task protocol or performance benchmark.
static void checkpoint(int fd, uint8_t phase) {
    if (fd < 0) return;
    ssize_t n;
    do { n = ::send(fd, &phase, 1, MSG_NOSIGNAL); } while (n < 0 && errno == EINTR);
    if (n != 1) throw std::runtime_error("test checkpoint send failed");
    uint8_t response = 0;
    do { n = ::recv(fd, &response, 1, MSG_WAITALL); } while (n < 0 && errno == EINTR);
    if (n != 1 || response != static_cast<uint8_t>(phase + 16))
        throw std::runtime_error("test checkpoint release failed");
}

struct Result {
    const std::string problem_id;
    const uint32_t seed;
    const uint64_t iterations;
    const std::vector<Snapshot> history;
    const Bits final_best_code;
    const int64_t final_best_fitness;
    const bool final_best_feasible;
    const Telemetry telemetry;
    std::shared_ptr<Counters> counts;

    Result(std::string id, uint32_t s, uint64_t n, std::vector<Snapshot> h,
           Bits best, int64_t score, bool feasible, Telemetry t,
           std::shared_ptr<Counters> c)
        : problem_id(std::move(id)), seed(s), iterations(n), history(std::move(h)),
          final_best_code(std::move(best)), final_best_fitness(score),
          final_best_feasible(feasible), telemetry(t), counts(std::move(c)) {
        counts->live_results.fetch_add(1);
    }
    Result(const Result&) = delete;
    Result& operator=(const Result&) = delete;
    ~Result() { counts->live_results.fetch_sub(1); }

    py::dict to_dict() const {
        // Called only AFTER solve() returns and pybind11 reacquires the GIL.
        py::list frames;
        for (const auto& h : history) {
            py::dict external;
            external["rng_state"] = h.rng_state;
            external["rng_draws"] = h.rng_draws;
            external["selected_item"] = h.selected_item;
            external["best_code"] = h.best_code;
            external["best_fitness"] = h.best_fitness;
            py::dict frame;
            frame["iteration"] = h.iteration;
            frame["label"] = h.label;
            frame["code"] = h.code;
            frame["raw_fitness"] = h.fitness;
            frame["feasible"] = h.feasible;
            frame["loads"] = h.loads;
            frame["external"] = external;
            frames.append(frame);
        }
        py::dict out;
        out["problem_id"] = problem_id;
        out["seed"] = seed;
        out["completed_iterations"] = iterations;
        out["history"] = frames;
        out["best_code"] = final_best_code;
        out["best_raw_fitness"] = final_best_fitness;
        out["best_feasible"] = final_best_feasible;
        return out;
    }

    py::dict measurements() const {
        py::dict d;
        d["enter_ns"] = telemetry.enter_ns;
        d["compute_start_ns"] = telemetry.compute_start_ns;
        d["middle_ns"] = telemetry.middle_ns;
        d["compute_finish_ns"] = telemetry.compute_finish_ns;
        d["exit_ns"] = telemetry.exit_ns;
        d["native_tid"] = telemetry.native_tid;
        d["problem_address"] = telemetry.problem_address;
        d["bank_address"] = telemetry.bank_address;
        return d;
    }
};

class Bank {
    const std::vector<std::shared_ptr<const Problem>> problems_;
    std::shared_ptr<Counters> counts_ = std::make_shared<Counters>();

    static std::vector<std::shared_ptr<const Problem>> prepare(
        const std::vector<std::string>& ids, const std::vector<Ints>& values,
        const std::vector<std::vector<Ints>>& weights, const std::vector<Ints>& capacities) {
        if (ids.size() != values.size() || ids.size() != weights.size() || ids.size() != capacities.size())
            throw std::invalid_argument("inconsistent fixture bank");
        std::vector<std::shared_ptr<const Problem>> result;
        for (size_t i = 0; i < ids.size(); ++i)
            result.push_back(std::make_shared<const Problem>(ids[i], values[i], weights[i], capacities[i]));
        return result;
    }

public:
    Bank(const std::vector<std::string>& ids, const std::vector<Ints>& values,
         const std::vector<std::vector<Ints>>& weights, const std::vector<Ints>& capacities)
        : problems_(prepare(ids, values, weights, capacities)) {}

    const Problem& find(const std::string& id) const {
        for (const auto& p : problems_) if (p->id == id) return *p;
        throw std::invalid_argument("unknown fixture problem");
    }

    py::list export_problems() const {
        py::list out;
        for (const auto& p : problems_) {
            py::dict d;
            d["problem_id"] = p->id;
            d["values"] = p->values;
            d["weights"] = p->weights;
            d["capacities"] = p->capacities;
            out.append(d);
        }
        return out;
    }

    py::dict diagnostics() const {
        py::dict d, addresses;
        for (const auto& p : problems_) addresses[py::str(p->id)] = reinterpret_cast<uintptr_t>(p.get());
        d["bank_address"] = reinterpret_cast<uintptr_t>(this);
        d["problem_addresses"] = addresses;
        d["prepared_problems"] = problems_.size();
        d["active"] = counts_->active.load();
        d["peak_active"] = counts_->peak_active.load();
        d["live_results"] = counts_->live_results.load();
        d["runs"] = counts_->runs.load();
        d["history_fitness_checks"] = counts_->history_fitness_checks.load();
        return d;
    }

    std::unique_ptr<Result> solve(const std::string& id, uint32_t seed, uint64_t iterations, int gate_fd) {
        // Native-only scope: no Python objects, callbacks, or file output.
        TaskScope scope(counts_);
        const Problem& p = find(id);
        Telemetry timing;
        timing.enter_ns = now_ns();
        timing.native_tid = static_cast<uint64_t>(::syscall(SYS_gettid));
        timing.problem_address = reinterpret_cast<uintptr_t>(&p);
        timing.bank_address = reinterpret_cast<uintptr_t>(this);
        Random rng(seed);
        Bits code(p.values.size(), 0), best = code;
        Ints loads(p.capacities.size(), 0);
        int64_t fitness = 0, best_fitness = 0;
        bool feasible = true;
        std::vector<Snapshot> frames;
        frames.reserve(iterations + 1);
        auto snapshot = [&](uint64_t i, int64_t selected) {
            frames.push_back(Snapshot{i, i == 0 ? "initialized" : "updated", code,
                fitness, feasible, loads, best, best_fitness, rng.state, rng.draws, selected});
        };
        snapshot(0, -1);
        checkpoint(gate_fd, 0);
        timing.compute_start_ns = now_ns();
        for (uint64_t i = 1; i <= iterations; ++i) {
            const size_t item = rng.next() % code.size();
            const int64_t change = code[item] ? -1 : 1;
            code[item] ^= 1;
            fitness += change * p.values[item];
            feasible = true;
            for (size_t d = 0; d < loads.size(); ++d) {
                loads[d] += change * p.weights[item][d];
                if (loads[d] > p.capacities[d]) feasible = false;
            }
            if (feasible && fitness > best_fitness) { best_fitness = fitness; best = code; }
            snapshot(i, static_cast<int64_t>(item));
            if (iterations > 1 && i == iterations / 2) {
                timing.middle_ns = now_ns();
                checkpoint(gate_fd, 1);
            }
        }
        timing.compute_finish_ns = now_ns();
        checkpoint(gate_fd, 2);

        // Final task validation is native. This also independently recomputes
        // all cached frame scores/loads without consuming RNG.
        for (const auto& h : frames) {
            const auto e = evaluate(p, h.code);
            const auto b = evaluate(p, h.best_code);
            if (e.fitness != h.fitness || e.feasible != h.feasible || e.loads != h.loads ||
                b.fitness != h.best_fitness || !b.feasible)
                throw std::logic_error("native final validation failed");
            counts_->history_fitness_checks.fetch_add(1);
        }
        const auto best_check = evaluate(p, best);
        timing.exit_ns = now_ns();
        return std::make_unique<Result>(id, seed, iterations, std::move(frames),
            std::move(best), best_fitness, best_check.feasible, timing, counts_);
    }
};

PYBIND11_MODULE(gate1_kernel, m) {
    m.doc() = "Temporary architecture correctness control; not a production solver";
    py::class_<Result>(m, "Result")
        .def("to_dict", &Result::to_dict)
        .def("measurements", &Result::measurements);
    py::class_<Bank>(m, "Bank")
        .def(py::init<const std::vector<std::string>&, const std::vector<Ints>&,
            const std::vector<std::vector<Ints>>&, const std::vector<Ints>&>())
        .def("export_problems", &Bank::export_problems)
        .def("diagnostics", &Bank::diagnostics)
        .def("solve", &Bank::solve, py::arg("problem_id"), py::arg("seed"),
            py::arg("iterations"), py::arg("gate_fd") = -1,
            py::call_guard<py::gil_scoped_release>());
}
