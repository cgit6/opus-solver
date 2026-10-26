// Isolated Linux page-protection feasibility only, NOT the production Bank.
#include <cstdint>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <sys/mman.h>
#include <sys/resource.h>
#include <unistd.h>

int main(int argc, char** argv) {
    rlimit limit{0, 0};
    if (setrlimit(RLIMIT_CORE, &limit)) return 2;
    const size_t page = static_cast<size_t>(sysconf(_SC_PAGESIZE));
    void* region = mmap(nullptr, page, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (region == MAP_FAILED) return 3;
    auto* preparing = static_cast<int64_t*>(region);
    for (int64_t i = 0; i < 64; ++i) preparing[i] = i;
    if (mprotect(region, page, PROT_READ)) return 4;
    const int64_t* data = preparing;
    if (argc > 1 && std::strcmp(argv[1], "write") == 0) {
        // Deliberate invalid write. volatile prevents dead-store removal.
        volatile int64_t* invalid = const_cast<int64_t*>(data);
        invalid[3] = 99;
        return 5;
    }
    int64_t total = 0;
    for (size_t i = 0; i < 64; ++i) total += data[i];
    std::cout << total << '\n';
    return munmap(region, page) == 0 ? 0 : 6;
}
