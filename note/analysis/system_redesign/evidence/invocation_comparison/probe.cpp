#ifdef BUILD_BINDING
#include <pybind11/pybind11.h>
namespace py = pybind11;
#endif
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <memory>
#include <stdexcept>
#include <thread>
#include <csignal>
#include <sys/mman.h>
#include <sys/socket.h>
#include <unistd.h>

using Clock = std::chrono::steady_clock;
static std::atomic<uint64_t> live_bytes{0};

// Planning-only synthetic kernel: identical deterministic arithmetic for all
// adapters. It has no Python callbacks and writes no experiment result files.
struct Result {
    uint64_t *data = nullptr;
    uint64_t size = 0, compute_ns = 0, rng = 0, checksum = 0;
    bool mapped = false;
    Result(uint64_t bytes, int fd): size(bytes), mapped(fd >= 0) {
        if (!bytes || bytes % 8) throw std::runtime_error("invalid byte count");
        if (mapped) {
            void *p = mmap(nullptr, bytes, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
            if (p == MAP_FAILED) throw std::runtime_error("mmap failed");
            data = static_cast<uint64_t *>(p);
        } else data = new uint64_t[bytes / 8];
        live_bytes += bytes;
    }
    ~Result() {
        if (mapped) munmap(data, size); else delete[] data;
        live_bytes -= size;
    }
};

std::unique_ptr<Result> run(uint64_t bytes, uint64_t seed, uint64_t action, int fd=-1) {
    // Delays are fault-test orchestration only, never benchmark workloads.
    if (action == 2) { std::this_thread::sleep_for(std::chrono::milliseconds(40)); raise(SIGABRT); }
    if (action == 3) std::this_thread::sleep_for(std::chrono::milliseconds(150));
    auto begin = Clock::now();
    auto result = std::make_unique<Result>(bytes, fd);
    if (action == 1) throw std::runtime_error("injected ordinary solver exception");
    uint64_t state = seed, sum = 0;
    for (uint64_t i=0; i<bytes/8; ++i) {
        state = state * UINT64_C(6364136223846793005) + UINT64_C(1442695040888963407);
        const uint64_t value = state ^ (i * UINT64_C(0x9e3779b97f4a7c15));
        result->data[i] = value;
        sum += value;
    }
    result->rng = state;
    result->checksum = sum;
    result->compute_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now()-begin).count();
    return result;
}

#ifdef BUILD_BINDING
PYBIND11_MODULE(invocation_probe, m) {
    py::class_<Result>(m, "Result", py::buffer_protocol())
        .def_buffer([](Result &r) {
            return py::buffer_info(r.data, 1, py::format_descriptor<unsigned char>::format(),
                                  1, {static_cast<py::ssize_t>(r.size)}, {1}, true);
        })
        .def_readonly("compute_ns", &Result::compute_ns)
        .def_readonly("rng", &Result::rng)
        .def_readonly("checksum", &Result::checksum);
    m.def("run", [](uint64_t bytes,uint64_t seed,uint64_t action) {
        return run(bytes,seed,action);
    }, py::call_guard<py::gil_scoped_release>());
    m.def("live_bytes", [](){return live_bytes.load();});
}
#else
static void send_all(int sock, const void *buffer, size_t n) {
    auto *p=static_cast<const char *>(buffer);
    while(n) {
        ssize_t k=send(sock,p,n,MSG_NOSIGNAL);
        if(k<=0) throw std::runtime_error("send failed");
        p+=k; n-=k;
    }
}
int main(int argc,char **argv) {
    if(argc != 2) return 4;
    int sock=std::stoi(argv[1]);
    for(;;) {
        uint64_t request[3]{};
        iovec io{request,sizeof(request)};
        alignas(cmsghdr) char control[CMSG_SPACE(sizeof(int))]{};
        msghdr msg{}; msg.msg_iov=&io; msg.msg_iovlen=1;
        msg.msg_control=control; msg.msg_controllen=sizeof(control);
        ssize_t n=recvmsg(sock,&msg,MSG_WAITALL);
        if(n==0) return 0;
        if(n!=sizeof(request) || (msg.msg_flags & MSG_CTRUNC)) return 5;
        if(request[2]==9) return 0;
        int fd=-1;
        for(cmsghdr *c=CMSG_FIRSTHDR(&msg);c;c=CMSG_NXTHDR(&msg,c))
            if(c->cmsg_level==SOL_SOCKET && c->cmsg_type==SCM_RIGHTS) std::memcpy(&fd,CMSG_DATA(c),sizeof(fd));
        try {
            auto result=run(request[0],request[1],request[2],fd);
            // Metadata is emitted only after the complete synthetic solve.
            uint64_t header[5]{0,result->size,result->compute_ns,result->rng,result->checksum};
            if(fd<0) {
                send_all(sock,header,sizeof(header));
                send_all(sock,result->data,result->size);
                result.reset();
            } else {
                result.reset(); // Python owns the mapping; native view can now go.
                send_all(sock,header,sizeof(header));
            }
            uint64_t released=live_bytes.load(); send_all(sock,&released,sizeof(released));
        } catch(const std::exception &) {
            uint64_t header[5]{1,0,0,0,0}; send_all(sock,header,sizeof(header));
            uint64_t released=live_bytes.load(); send_all(sock,&released,sizeof(released));
        }
        if(fd>=0) close(fd);
    }
}
#endif
