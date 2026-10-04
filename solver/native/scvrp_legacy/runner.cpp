#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#include <cmath>
#include <array>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include "common/dependences.h"
#include "common/local_search.h"
#include "metaheuristic/differential_evolution.h"

int NP;

namespace {

constexpr int MAX_SA_PROBE_CASES = 16;
constexpr int MAX_GENERATION_PROBE_TRANSITIONS = 111;

struct SAAcceptanceCase {
    unsigned int rng_seed = 0;
    int target_cost = 0;
    int trial_cost = 0;
    double temperature = 0.0;
};

struct Input {
    int customers = 0;
    int vehicles = 0;
    int capacity = 0;
    int best_known = 0;
    unsigned int seed = 0;
    int de_technique = 0;
    double start_temperature = 0.0;
    double cooling_rate = 0.0;
    int iterations_per_temperature = 0;
    std::string termination;
    int limit = 0;
    int max_transitions = 0;
    bool trace = false;
    bool process_trace = false;
    int probe_target = -1;
    int probe_reinsert_customer = -1;
    int probe_reinsert_new_route = -1;
    int probe_two_swap_transfer_customer = -1;
    int probe_strong_drop_transfer_customer = -1;
    bool probe_local_search = false;
    std::vector<SAAcceptanceCase> probe_sa_cases;
    bool probe_new_generation = false;
    std::vector<int> demands;
    std::vector<std::vector<int>> distances;
    std::vector<std::vector<int>> fixed_routes;
    std::vector<int> fixed_capacities;
};

struct Snapshot {
    int generation = 0;
    int objective = 0;
    int feasible_solutions = 0;
    bool feasible = false;
    int transfer_vehicle_count = 0;
    std::vector<std::vector<int>> routes;
    std::vector<int> transferred_customers;
};

struct ProcessTraceEntry {
    int generation = 0;
    std::array<uint8_t, 32> canonical_digest{};
    uint32_t rng_state = 0;
    uint64_t rng_draw_count = 0;
};

class Sha256 {
public:
    Sha256()
        : state_{
              0x6a09e667U, 0xbb67ae85U, 0x3c6ef372U, 0xa54ff53aU,
              0x510e527fU, 0x9b05688cU, 0x1f83d9abU, 0x5be0cd19U,
          } {}

    void update(const uint8_t* data, size_t length) {
        total_bytes_ += length;
        for (size_t index = 0; index < length; ++index) {
            buffer_[buffer_length_++] = data[index];
            if (buffer_length_ == buffer_.size()) {
                transform(buffer_.data());
                buffer_length_ = 0;
            }
        }
    }

    void update(const char* data, size_t length) {
        update(reinterpret_cast<const uint8_t*>(data), length);
    }

    std::array<uint8_t, 32> finish() {
        const uint64_t bit_length = total_bytes_ * 8U;
        buffer_[buffer_length_++] = 0x80U;
        if (buffer_length_ > 56) {
            while (buffer_length_ < buffer_.size()) {
                buffer_[buffer_length_++] = 0U;
            }
            transform(buffer_.data());
            buffer_length_ = 0;
        }
        while (buffer_length_ < 56) {
            buffer_[buffer_length_++] = 0U;
        }
        for (int index = 0; index < 8; ++index) {
            buffer_[63 - index] = static_cast<uint8_t>(bit_length >> (8 * index));
        }
        transform(buffer_.data());

        std::array<uint8_t, 32> digest{};
        for (size_t index = 0; index < state_.size(); ++index) {
            digest[index * 4] = static_cast<uint8_t>(state_[index] >> 24);
            digest[index * 4 + 1] = static_cast<uint8_t>(state_[index] >> 16);
            digest[index * 4 + 2] = static_cast<uint8_t>(state_[index] >> 8);
            digest[index * 4 + 3] = static_cast<uint8_t>(state_[index]);
        }
        return digest;
    }

private:
    static uint32_t rotate_right(uint32_t value, uint32_t shift) {
        return (value >> shift) | (value << (32U - shift));
    }

    void transform(const uint8_t* block) {
        static constexpr uint32_t constants[64] = {
            0x428a2f98U, 0x71374491U, 0xb5c0fbcfU, 0xe9b5dba5U,
            0x3956c25bU, 0x59f111f1U, 0x923f82a4U, 0xab1c5ed5U,
            0xd807aa98U, 0x12835b01U, 0x243185beU, 0x550c7dc3U,
            0x72be5d74U, 0x80deb1feU, 0x9bdc06a7U, 0xc19bf174U,
            0xe49b69c1U, 0xefbe4786U, 0x0fc19dc6U, 0x240ca1ccU,
            0x2de92c6fU, 0x4a7484aaU, 0x5cb0a9dcU, 0x76f988daU,
            0x983e5152U, 0xa831c66dU, 0xb00327c8U, 0xbf597fc7U,
            0xc6e00bf3U, 0xd5a79147U, 0x06ca6351U, 0x14292967U,
            0x27b70a85U, 0x2e1b2138U, 0x4d2c6dfcU, 0x53380d13U,
            0x650a7354U, 0x766a0abbU, 0x81c2c92eU, 0x92722c85U,
            0xa2bfe8a1U, 0xa81a664bU, 0xc24b8b70U, 0xc76c51a3U,
            0xd192e819U, 0xd6990624U, 0xf40e3585U, 0x106aa070U,
            0x19a4c116U, 0x1e376c08U, 0x2748774cU, 0x34b0bcb5U,
            0x391c0cb3U, 0x4ed8aa4aU, 0x5b9cca4fU, 0x682e6ff3U,
            0x748f82eeU, 0x78a5636fU, 0x84c87814U, 0x8cc70208U,
            0x90befffaU, 0xa4506cebU, 0xbef9a3f7U, 0xc67178f2U,
        };
        uint32_t words[64]{};
        for (int index = 0; index < 16; ++index) {
            const int offset = index * 4;
            words[index] =
                (static_cast<uint32_t>(block[offset]) << 24) |
                (static_cast<uint32_t>(block[offset + 1]) << 16) |
                (static_cast<uint32_t>(block[offset + 2]) << 8) |
                static_cast<uint32_t>(block[offset + 3]);
        }
        for (int index = 16; index < 64; ++index) {
            const uint32_t s0 =
                rotate_right(words[index - 15], 7) ^
                rotate_right(words[index - 15], 18) ^
                (words[index - 15] >> 3);
            const uint32_t s1 =
                rotate_right(words[index - 2], 17) ^
                rotate_right(words[index - 2], 19) ^
                (words[index - 2] >> 10);
            words[index] = words[index - 16] + s0 + words[index - 7] + s1;
        }

        uint32_t a = state_[0];
        uint32_t b = state_[1];
        uint32_t c = state_[2];
        uint32_t d = state_[3];
        uint32_t e = state_[4];
        uint32_t f = state_[5];
        uint32_t g = state_[6];
        uint32_t h = state_[7];
        for (int index = 0; index < 64; ++index) {
            const uint32_t sum1 =
                rotate_right(e, 6) ^ rotate_right(e, 11) ^ rotate_right(e, 25);
            const uint32_t choose = (e & f) ^ ((~e) & g);
            const uint32_t temporary1 = h + sum1 + choose + constants[index] + words[index];
            const uint32_t sum0 =
                rotate_right(a, 2) ^ rotate_right(a, 13) ^ rotate_right(a, 22);
            const uint32_t majority = (a & b) ^ (a & c) ^ (b & c);
            const uint32_t temporary2 = sum0 + majority;
            h = g;
            g = f;
            f = e;
            e = d + temporary1;
            d = c;
            c = b;
            b = a;
            a = temporary1 + temporary2;
        }
        state_[0] += a;
        state_[1] += b;
        state_[2] += c;
        state_[3] += d;
        state_[4] += e;
        state_[5] += f;
        state_[6] += g;
        state_[7] += h;
    }

    std::array<uint32_t, 8> state_;
    std::array<uint8_t, 64> buffer_{};
    size_t buffer_length_ = 0;
    uint64_t total_bytes_ = 0;
};

void sha_update_u8(Sha256& hasher, uint8_t value) {
    hasher.update(&value, 1);
}

void sha_update_u32_le(Sha256& hasher, uint32_t value) {
    uint8_t encoded[4];
    for (int index = 0; index < 4; ++index) {
        encoded[index] = static_cast<uint8_t>(value >> (8 * index));
    }
    hasher.update(encoded, sizeof(encoded));
}

void sha_update_i32_le(Sha256& hasher, int32_t value) {
    sha_update_u32_le(hasher, static_cast<uint32_t>(value));
}

void sha_update_u64_le(Sha256& hasher, uint64_t value) {
    uint8_t encoded[8];
    for (int index = 0; index < 8; ++index) {
        encoded[index] = static_cast<uint8_t>(value >> (8 * index));
    }
    hasher.update(encoded, sizeof(encoded));
}

void sha_update_individual(
    Sha256& hasher,
    const Individual* individual,
    int customers,
    int vehicles,
    int transfer_routes
) {
    if (individual == nullptr || individual->vehicles_num_K != vehicles) {
        throw std::runtime_error("process trace individual route count mismatch");
    }
    std::vector<bool> routed(customers, false);
    routed[0] = true;
    int routed_count = 1;
    for (int route_index = 0; route_index < vehicles; ++route_index) {
        const int route_length = individual->routes_end[route_index];
        if (route_length < 0 || route_length >= customers) {
            throw std::runtime_error("process trace route length is invalid");
        }
        sha_update_u32_le(hasher, static_cast<uint32_t>(route_length));
        for (int position = 0; position < route_length; ++position) {
            const int customer = individual->routes[route_index][position];
            if (customer <= 0 || customer >= customers || routed[customer]) {
                throw std::runtime_error("process trace routes are not a permutation");
            }
            routed[customer] = true;
            ++routed_count;
            sha_update_i32_le(hasher, customer);
        }
    }
    if (routed_count != customers) {
        throw std::runtime_error("process trace routes omit a customer");
    }

    for (int axis = 0; axis < 2; ++axis) {
        for (int customer = 0; customer < customers; ++customer) {
            sha_update_i32_le(hasher, individual->positions[axis][customer]);
        }
    }
    for (int customer = 0; customer < customers; ++customer) {
        const int transfer = individual->Customer_Transfer[customer];
        if (transfer != 0 && transfer != 1) {
            throw std::runtime_error("process trace transfer mask is not boolean");
        }
        sha_update_i32_le(hasher, transfer);
    }
    if (individual->feasible != 0 && individual->feasible != 1) {
        throw std::runtime_error("process trace feasible flag is not boolean");
    }
    sha_update_i32_le(hasher, individual->cost);
    sha_update_u8(hasher, static_cast<uint8_t>(individual->feasible));
    for (int route_index = 0; route_index < vehicles; ++route_index) {
        sha_update_i32_le(hasher, individual->capacities_free[route_index]);
    }
    for (int route_index = 0; route_index < transfer_routes; ++route_index) {
        sha_update_i32_le(
            hasher,
            individual->Transfer_Car_Capacities_Free[route_index]
        );
    }
    sha_update_i32_le(hasher, individual->Transfer_Car_Number);
    sha_update_i32_le(
        hasher,
        individual->Transfer_Car_Totol_Capacities_Free
    );
}

ProcessTraceEntry process_trace_entry(
    const Generation* generation,
    int customers,
    int vehicles,
    int transfer_routes
) {
    if (generation == nullptr) {
        throw std::runtime_error("process trace generation is null");
    }
    int best_index = -1;
    int best_identity_matches = 0;
    for (int index = 0; index < NP; ++index) {
        if (generation->individuals[index] == generation->best_solution) {
            best_index = index;
            ++best_identity_matches;
        }
    }
    if (best_identity_matches > 1) {
        throw std::runtime_error("process trace best appears in multiple slots");
    }

    ProcessTraceEntry result;
    result.generation = generation->id;
    result.rng_state = scvrp_msvc_rand_state();
    result.rng_draw_count = scvrp_msvc_rand_draw_count();

    static constexpr char schema[] = "SCVRP_FULL_POP_V1";
    Sha256 hasher;
    hasher.update(schema, sizeof(schema) - 1);
    sha_update_i32_le(hasher, generation->id);
    sha_update_u32_le(hasher, static_cast<uint32_t>(NP));
    sha_update_u32_le(hasher, static_cast<uint32_t>(customers));
    sha_update_u32_le(hasher, static_cast<uint32_t>(vehicles));
    sha_update_u32_le(hasher, static_cast<uint32_t>(transfer_routes));
    sha_update_i32_le(hasher, generation->feasible_solutions_num);
    sha_update_i32_le(hasher, best_index);
    sha_update_u32_le(hasher, result.rng_state);
    sha_update_u64_le(hasher, result.rng_draw_count);
    for (int index = 0; index < NP; ++index) {
        sha_update_individual(
            hasher,
            generation->individuals[index],
            customers,
            vehicles,
            transfer_routes
        );
    }
    sha_update_individual(
        hasher,
        generation->best_solution,
        customers,
        vehicles,
        transfer_routes
    );
    result.canonical_digest = hasher.finish();
    return result;
}

std::string digest_hex(const std::array<uint8_t, 32>& digest) {
    std::ostringstream output;
    output << std::hex << std::setfill('0');
    for (uint8_t value : digest) {
        output << std::setw(2) << static_cast<unsigned int>(value);
    }
    return output.str();
}

std::array<uint8_t, 32> process_trace_digest(
    const std::vector<ProcessTraceEntry>& trace
) {
    static constexpr char schema[] = "SCVRP_FULL_TRACE_V1";
    Sha256 hasher;
    hasher.update(schema, sizeof(schema) - 1);
    sha_update_u32_le(hasher, static_cast<uint32_t>(trace.size()));
    for (const ProcessTraceEntry& entry : trace) {
        hasher.update(entry.canonical_digest.data(), entry.canonical_digest.size());
    }
    return hasher.finish();
}

void expect(const char* expected) {
    std::string actual;
    if (!(std::cin >> actual) || actual != expected) {
        throw std::runtime_error(
            std::string("expected token '") + expected + "', got '" + actual + "'"
        );
    }
}

Input read_input() {
    Input input;
    expect("SCVRP_LEGACY_RUNNER_V1");
    expect("customers");
    std::cin >> input.customers;
    expect("vehicles");
    std::cin >> input.vehicles;
    expect("capacity");
    std::cin >> input.capacity;
    expect("best_known");
    std::cin >> input.best_known;
    expect("seed");
    std::cin >> input.seed;
    expect("de_technique");
    std::cin >> input.de_technique;
    expect("start_temperature");
    std::cin >> input.start_temperature;
    expect("cooling_rate");
    std::cin >> input.cooling_rate;
    expect("iterations_per_temperature");
    std::cin >> input.iterations_per_temperature;
    expect("termination");
    std::cin >> input.termination;
    expect("limit");
    std::cin >> input.limit;
    expect("max_transitions");
    std::cin >> input.max_transitions;
    int trace = 0;
    expect("trace");
    std::cin >> trace;
    input.trace = trace != 0;
    int process_trace = 0;
    expect("process_trace");
    std::cin >> process_trace;
    if (process_trace != 0 && process_trace != 1) {
        throw std::runtime_error("process_trace must be 0 or 1");
    }
    input.process_trace = process_trace != 0;
    expect("probe_target");
    std::cin >> input.probe_target;
    expect("probe_reinsert_customer");
    std::cin >> input.probe_reinsert_customer;
    expect("probe_reinsert_new_route");
    std::cin >> input.probe_reinsert_new_route;
    expect("probe_two_swap_transfer_customer");
    std::cin >> input.probe_two_swap_transfer_customer;
    expect("probe_strong_drop_transfer_customer");
    std::cin >> input.probe_strong_drop_transfer_customer;
    int probe_local_search = 0;
    expect("probe_local_search");
    std::cin >> probe_local_search;
    if (probe_local_search != 0 && probe_local_search != 1) {
        throw std::runtime_error("probe_local_search must be 0 or 1");
    }
    input.probe_local_search = probe_local_search != 0;
    int probe_sa_case_count = 0;
    expect("probe_sa_case_count");
    std::cin >> probe_sa_case_count;
    if (probe_sa_case_count < 0 || probe_sa_case_count > MAX_SA_PROBE_CASES) {
        throw std::runtime_error("invalid SA acceptance probe case count");
    }
    input.probe_sa_cases.reserve(probe_sa_case_count);
    for (int index = 0; index < probe_sa_case_count; ++index) {
        uint64_t rng_seed = 0;
        long long target_cost = 0;
        long long trial_cost = 0;
        double temperature = 0.0;
        expect("probe_sa_case");
        std::cin >> rng_seed >> target_cost >> trial_cost >> temperature;
        if (!std::cin ||
            rng_seed > std::numeric_limits<uint32_t>::max() ||
            target_cost < 0 ||
            target_cost > std::numeric_limits<int>::max() ||
            trial_cost < 0 ||
            trial_cost > std::numeric_limits<int>::max() ||
            !std::isfinite(temperature) || temperature <= 0.0) {
            throw std::runtime_error("invalid SA acceptance probe case");
        }
        SAAcceptanceCase probe_case;
        probe_case.rng_seed = static_cast<unsigned int>(rng_seed);
        probe_case.target_cost = static_cast<int>(target_cost);
        probe_case.trial_cost = static_cast<int>(trial_cost);
        probe_case.temperature = temperature;
        input.probe_sa_cases.push_back(probe_case);
    }
    int probe_new_generation = 0;
    expect("probe_new_generation");
    std::cin >> probe_new_generation;
    if (probe_new_generation != 0 && probe_new_generation != 1) {
        throw std::runtime_error("probe_new_generation must be 0 or 1");
    }
    input.probe_new_generation = probe_new_generation != 0;

    if (!std::cin || input.customers <= 1 || input.vehicles <= 0 || input.capacity <= 0) {
        throw std::runtime_error("invalid SCVRP dimensions");
    }
    if (input.seed == 0 || input.de_technique != 2) {
        throw std::runtime_error("compatibility profile requires seed > 0 and de_technique 2");
    }
    if (!(input.start_temperature > 0.0) || !(input.cooling_rate > 0.0) ||
        !(input.cooling_rate <= 1.0) || input.iterations_per_temperature <= 0) {
        throw std::runtime_error("invalid simulated-annealing parameters");
    }
    if ((input.termination != "fixed_iterations" &&
         input.termination != "legacy_temperature_stagnation") || input.limit < 0 ||
        input.max_transitions <= 0 || input.probe_target < -1) {
        throw std::runtime_error("invalid termination mode or limit");
    }
    if ((input.probe_reinsert_customer == -1) !=
        (input.probe_reinsert_new_route == -1)) {
        throw std::runtime_error("reinsertion probe fields must be provided together");
    }
    if (input.probe_reinsert_customer != -1 &&
        (input.probe_target == -1 || input.probe_reinsert_customer <= 0 ||
         input.probe_reinsert_customer >= input.customers ||
         input.probe_reinsert_new_route < 0 ||
         input.probe_reinsert_new_route >= input.vehicles)) {
        throw std::runtime_error("invalid reinsertion probe target");
    }
    if (input.probe_two_swap_transfer_customer != -1 &&
        (input.probe_target == -1 ||
         input.probe_two_swap_transfer_customer <= 0 ||
         input.probe_two_swap_transfer_customer >= input.customers)) {
        throw std::runtime_error("invalid two-swap transfer probe customer");
    }
    if (input.probe_strong_drop_transfer_customer != -1 &&
        (input.probe_target == -1 ||
         input.probe_strong_drop_transfer_customer <= 0 ||
         input.probe_strong_drop_transfer_customer >= input.customers)) {
        throw std::runtime_error("invalid strong-drop transfer probe customer");
    }
    if (input.probe_local_search && input.probe_target == -1) {
        throw std::runtime_error("probe_target is required for local-search probe");
    }
    if (!input.probe_sa_cases.empty() && input.probe_target == -1) {
        throw std::runtime_error("probe_target is required for SA acceptance probe");
    }
    if (input.probe_new_generation &&
        (input.probe_target != -1 || input.termination != "fixed_iterations" ||
         input.limit < 1 || input.limit > MAX_GENERATION_PROBE_TRANSITIONS ||
         input.trace)) {
        throw std::runtime_error(
            "new-generation probe requires an isolated fixed iteration"
        );
    }
    if (input.process_trace &&
        (input.probe_target != -1 || input.probe_new_generation)) {
        throw std::runtime_error(
            "process_trace is only available for a complete loop run"
        );
    }

    expect("demands");
    input.demands.resize(input.customers);
    for (int& demand : input.demands) {
        std::cin >> demand;
        if (demand < 0) {
            throw std::runtime_error("demands must be non-negative");
        }
    }
    if (input.demands[0] != 0) {
        throw std::runtime_error("depot demand must be zero");
    }

    expect("distance_matrix");
    input.distances.assign(input.customers, std::vector<int>(input.customers));
    for (auto& row : input.distances) {
        for (int& distance : row) {
            std::cin >> distance;
            if (distance < 0) {
                throw std::runtime_error("distances must be non-negative");
            }
        }
    }

    int fixed_route_count = 0;
    expect("fixed_route_count");
    std::cin >> fixed_route_count;
    if (fixed_route_count <= 0) {
        throw std::runtime_error("fixed_route_count must be positive");
    }
    input.fixed_routes.resize(fixed_route_count);
    input.fixed_capacities.resize(fixed_route_count);
    std::vector<bool> seen(input.customers, false);
    seen[0] = true;
    for (int route_index = 0; route_index < fixed_route_count; ++route_index) {
        int capacity_free = 0;
        int route_size = 0;
        expect("fixed_route");
        std::cin >> capacity_free >> route_size;
        if (capacity_free < 0 || route_size < 0) {
            throw std::runtime_error("invalid fixed route header");
        }
        input.fixed_capacities[route_index] = capacity_free;
        auto& route = input.fixed_routes[route_index];
        route.resize(route_size);
        for (int& customer : route) {
            std::cin >> customer;
            if (customer <= 0 || customer >= input.customers || seen[customer]) {
                throw std::runtime_error("fixed routes must contain every customer once");
            }
            seen[customer] = true;
        }
    }
    for (bool customer_seen : seen) {
        if (!customer_seen) {
            throw std::runtime_error("fixed routes are missing a customer");
        }
    }
    expect("END");
    if (!std::cin) {
        throw std::runtime_error("truncated runner input");
    }
    return input;
}

Customer* make_customers(const Input& input) {
    Customer* customers = new Customer[input.customers];
    for (int i = 0; i < input.customers; ++i) {
        customers[i].id = i;
        customers[i].demand = input.demands[i];
        customers[i].x = 0.0;
        customers[i].y = 0.0;
    }
    return customers;
}

int** make_distances(const Input& input) {
    int** distances = static_cast<int**>(malloc(input.customers * sizeof(int*)));
    for (int row = 0; row < input.customers; ++row) {
        distances[row] = static_cast<int*>(malloc(input.customers * sizeof(int)));
        for (int column = 0; column < input.customers; ++column) {
            distances[row][column] = input.distances[row][column];
        }
    }
    return distances;
}

Individual* make_fixed_routes(const Input& input) {
    Individual* fixed = Fixed_Route_individual_init(
        input.customers,
        static_cast<int>(input.fixed_routes.size())
    );
    for (int route_index = 0; route_index < fixed->vehicles_num_K; ++route_index) {
        const auto& route = input.fixed_routes[route_index];
        fixed->routes_end[route_index] = static_cast<int>(route.size());
        fixed->capacities_free[route_index] = input.fixed_capacities[route_index];
        for (int position = 0; position < static_cast<int>(route.size()); ++position) {
            const int customer = route[position];
            fixed->routes[route_index][position] = customer;
            fixed->positions[0][customer] = route_index;
            fixed->positions[1][customer] = position;
        }
    }
    return fixed;
}

void free_fixed_routes(Individual* fixed) {
    for (int route = 0; route < fixed->vehicles_num_K; ++route) {
        free(fixed->routes[route]);
    }
    free(fixed->routes);
    free(fixed->positions[0]);
    free(fixed->positions[1]);
    free(fixed->positions);
    free(fixed->routes_end);
    free(fixed->capacities_free);
    free(fixed->Customer_Transfer);
    free(fixed);
}

Individual* make_defined_state_clone(
    const Individual* source,
    int customers,
    Individual* fixed_routes
) {
    // The archived hard clone omits capacities_free.  Probe branches require
    // every reevaluated field and must not share mutable arrays with each other.
    Individual* clone = individual_init(
        customers,
        source->vehicles_num_K,
        fixed_routes
    );
    for (int route_index = 0; route_index < source->vehicles_num_K; ++route_index) {
        for (int customer_index = 0; customer_index < customers; ++customer_index) {
            clone->routes[route_index][customer_index] = 0;
        }
        clone->routes_end[route_index] = source->routes_end[route_index];
        clone->capacities_free[route_index] = source->capacities_free[route_index];
        for (int position = 0; position < source->routes_end[route_index]; ++position) {
            clone->routes[route_index][position] = source->routes[route_index][position];
        }
    }
    for (int customer = 0; customer < customers; ++customer) {
        clone->positions[0][customer] = source->positions[0][customer];
        clone->positions[1][customer] = source->positions[1][customer];
        clone->Customer_Transfer[customer] = source->Customer_Transfer[customer];
    }
    for (int route = 0; route < fixed_routes->vehicles_num_K; ++route) {
        clone->Transfer_Car_Capacities_Free[route] =
            source->Transfer_Car_Capacities_Free[route];
    }
    clone->cost = source->cost;
    clone->feasible = source->feasible;
    clone->cloned = source->cloned;
    clone->vehicles_num_K = source->vehicles_num_K;
    clone->Transfer_Car_Number = source->Transfer_Car_Number;
    clone->Transfer_Car_Totol_Capacities_Free =
        source->Transfer_Car_Totol_Capacities_Free;
    return clone;
}

Snapshot snapshot(const Generation* generation, int customers) {
    const Individual* best = generation->best_solution;
    Snapshot result;
    result.generation = generation->id;
    result.objective = best->cost;
    result.feasible_solutions = generation->feasible_solutions_num;
    result.feasible = best->feasible != 0;
    result.transfer_vehicle_count = best->Transfer_Car_Number;
    result.routes.resize(best->vehicles_num_K);
    for (int route_index = 0; route_index < best->vehicles_num_K; ++route_index) {
        auto& route = result.routes[route_index];
        route.assign(
            best->routes[route_index],
            best->routes[route_index] + best->routes_end[route_index]
        );
    }
    for (int customer = 1; customer < customers; ++customer) {
        if (best->Customer_Transfer[customer] == 1) {
            result.transferred_customers.push_back(customer);
        }
    }
    return result;
}

void write_int_array(const std::vector<int>& values) {
    std::cout << '[';
    for (size_t index = 0; index < values.size(); ++index) {
        if (index != 0) {
            std::cout << ',';
        }
        std::cout << values[index];
    }
    std::cout << ']';
}

void write_routes(const std::vector<std::vector<int>>& routes) {
    std::cout << '[';
    for (size_t index = 0; index < routes.size(); ++index) {
        if (index != 0) {
            std::cout << ',';
        }
        write_int_array(routes[index]);
    }
    std::cout << ']';
}

void write_snapshot(const Snapshot& value) {
    std::cout << "{\"generation\":" << value.generation
              << ",\"objective\":" << value.objective
              << ",\"feasible_solutions\":" << value.feasible_solutions
              << ",\"feasible\":" << (value.feasible ? "true" : "false")
              << ",\"transfer_vehicle_count\":" << value.transfer_vehicle_count
              << ",\"routes\":";
    write_routes(value.routes);
    std::cout << ",\"transferred_customers\":";
    write_int_array(value.transferred_customers);
    std::cout << '}';
}

void write_individual_genome(const Individual* individual, int customers) {
    std::vector<std::vector<int>> routes(individual->vehicles_num_K);
    for (int route_index = 0; route_index < individual->vehicles_num_K; ++route_index) {
        routes[route_index].assign(
            individual->routes[route_index],
            individual->routes[route_index] + individual->routes_end[route_index]
        );
    }
    std::cout << "{\"routes\":";
    write_routes(routes);
    std::cout << ",\"positions\":[";
    for (int axis = 0; axis < 2; ++axis) {
        if (axis != 0) {
            std::cout << ',';
        }
        std::cout << '[';
        for (int customer = 0; customer < customers; ++customer) {
            if (customer != 0) {
                std::cout << ',';
            }
            std::cout << individual->positions[axis][customer];
        }
        std::cout << ']';
    }
    std::cout << "],\"transfer_mask\":[";
    for (int customer = 0; customer < customers; ++customer) {
        if (customer != 0) {
            std::cout << ',';
        }
        std::cout << individual->Customer_Transfer[customer];
    }
    std::cout << "]}";
}

void write_individual_defined_state(
    const Individual* individual,
    int customers,
    int transfer_routes
) {
    std::vector<std::vector<int>> routes(individual->vehicles_num_K);
    for (int route_index = 0; route_index < individual->vehicles_num_K; ++route_index) {
        routes[route_index].assign(
            individual->routes[route_index],
            individual->routes[route_index] + individual->routes_end[route_index]
        );
    }
    std::cout << "{\"routes\":";
    write_routes(routes);
    std::cout << ",\"positions\":[";
    for (int axis = 0; axis < 2; ++axis) {
        if (axis != 0) {
            std::cout << ',';
        }
        std::cout << '[';
        for (int customer = 0; customer < customers; ++customer) {
            if (customer != 0) {
                std::cout << ',';
            }
            std::cout << individual->positions[axis][customer];
        }
        std::cout << ']';
    }
    std::cout << "],\"transfer_mask\":[";
    for (int customer = 0; customer < customers; ++customer) {
        if (customer != 0) {
            std::cout << ',';
        }
        std::cout << individual->Customer_Transfer[customer];
    }
    std::cout << "],\"cost\":" << individual->cost
              << ",\"feasible\":" << (individual->feasible ? "true" : "false")
              << ",\"route_capacities_free\":[";
    for (int route = 0; route < individual->vehicles_num_K; ++route) {
        if (route != 0) {
            std::cout << ',';
        }
        std::cout << individual->capacities_free[route];
    }
    std::cout << "],\"transfer_capacities_free\":[";
    for (int route = 0; route < transfer_routes; ++route) {
        if (route != 0) {
            std::cout << ',';
        }
        std::cout << individual->Transfer_Car_Capacities_Free[route];
    }
    std::cout << "],\"transfer_vehicle_count\":"
              << individual->Transfer_Car_Number
              << ",\"transfer_total_capacity_free\":"
              << individual->Transfer_Car_Totol_Capacities_Free
              << '}';
}

void write_rng_fingerprint(uint32_t state, uint64_t draw_count);

void write_generation_defined_state(
    const Generation* generation,
    int customers,
    int transfer_routes
) {
    int best_index = -1;
    for (int index = 0; index < NP; ++index) {
        if (generation->individuals[index] == generation->best_solution) {
            best_index = index;
            break;
        }
    }

    std::cout << "{\"generation_id\":" << generation->id
              << ",\"best_index\":" << best_index
              << ",\"feasible_solutions\":"
              << generation->feasible_solutions_num
              << ",\"individuals\":[";
    for (int index = 0; index < NP; ++index) {
        if (index != 0) {
            std::cout << ',';
        }
        write_individual_defined_state(
            generation->individuals[index],
            customers,
            transfer_routes
        );
    }
    std::cout << "],\"best\":";
    write_individual_defined_state(
        generation->best_solution,
        customers,
        transfer_routes
    );
    std::cout << ",\"rng\":";
    write_rng_fingerprint(
        scvrp_msvc_rand_state(),
        scvrp_msvc_rand_draw_count()
    );
    std::cout << '}';
}

void write_rng_fingerprint(uint32_t state, uint64_t draw_count) {
    std::cout << "{\"state\":" << state << ",\"draw_count\":" << draw_count << '}';
}

void restore_probe_rng_prefix(unsigned int seed, uint64_t draw_count) {
    // The archived RNG exposes no setter.  Replaying its bounded probe prefix
    // restores both state and draw count without changing the compatibility
    // shim or leaking this stochastic test branch into later probes.
    srand(seed);
    for (uint64_t draw = 0; draw < draw_count; ++draw) {
        (void)rand();
    }
}

std::string double_hex(double value) {
    std::ostringstream stream;
    stream << std::hexfloat << value;
    return stream.str();
}

}  // namespace

int main(int argc, char** argv) {
    try {
        if (argc == 2 && std::string(argv[1]) == "--self-test") {
            srand(1);
            const int expected[] = {41, 18467, 6334, 26500, 19169};
            for (int value : expected) {
                if (rand() != value) {
                    throw std::runtime_error("MSVC RNG self-test failed");
                }
            }
            const auto verify_sha256 = [](const std::string& input,
                                          const char* expected_digest) {
                Sha256 sha256;
                sha256.update(input.data(), input.size());
                if (digest_hex(sha256.finish()) != expected_digest) {
                    throw std::runtime_error("SHA-256 self-test failed");
                }
            };
            verify_sha256(
                "",
                "e3b0c44298fc1c149afbf4c8996fb924"
                "27ae41e4649b934ca495991b7852b855"
            );
            verify_sha256(
                "abc",
                "ba7816bf8f01cfea414140de5dae2223"
                "b00361a396177a9cb410ff61f20015ad"
            );
            verify_sha256(
                std::string(55, 'a'),
                "9f4390f8d30c2dd92ec9f095b65e2b9"
                "ae9b0a925a5258e241c9f1e910f734318"
            );
            verify_sha256(
                std::string(56, 'a'),
                "b35439a4ac6f0948b6d6f9e3c6af0f5"
                "f590ce20f1bde7090ef7970686ec6738a"
            );
            verify_sha256(
                std::string(64, 'a'),
                "ffe054fe7ae0cb6dc65c3af9b61d5209"
                "f439851db43d0ba5997337df154668eb"
            );

            const auto expect_process_trace_rejection = [](
                const char* expected_message,
                const auto& action
            ) {
                try {
                    action();
                } catch (const std::runtime_error& error) {
                    if (std::string(error.what()) == expected_message) {
                        return;
                    }
                    throw std::runtime_error(
                        std::string("unexpected process-trace guard error: ") +
                        error.what()
                    );
                }
                throw std::runtime_error(
                    std::string("process-trace guard did not reject: ") +
                    expected_message
                );
            };

            int route_values[] = {1, 2, 0};
            int* routes[] = {route_values};
            int position_routes[] = {0, 0, 0};
            int position_indices[] = {0, 0, 1};
            int* positions[] = {position_routes, position_indices};
            int routes_end[] = {2};
            int capacities_free[] = {0};
            int transfer_mask[] = {0, 0, 0};
            int transfer_capacities_free[] = {0};
            Individual trace_fixture{};
            trace_fixture.routes = routes;
            trace_fixture.positions = positions;
            trace_fixture.routes_end = routes_end;
            trace_fixture.capacities_free = capacities_free;
            trace_fixture.Customer_Transfer = transfer_mask;
            trace_fixture.Transfer_Car_Capacities_Free =
                transfer_capacities_free;
            trace_fixture.cost = 0;
            trace_fixture.feasible = 1;
            trace_fixture.vehicles_num_K = 1;
            trace_fixture.Transfer_Car_Number = 0;
            trace_fixture.Transfer_Car_Totol_Capacities_Free = 0;

            const auto hash_trace_fixture = [&trace_fixture]() {
                Sha256 hasher;
                sha_update_individual(hasher, &trace_fixture, 3, 1, 1);
                (void)hasher.finish();
            };
            hash_trace_fixture();

            expect_process_trace_rejection(
                "process trace individual route count mismatch",
                []() {
                    Sha256 hasher;
                    sha_update_individual(hasher, nullptr, 3, 1, 1);
                }
            );
            trace_fixture.vehicles_num_K = 2;
            expect_process_trace_rejection(
                "process trace individual route count mismatch",
                hash_trace_fixture
            );
            trace_fixture.vehicles_num_K = 1;

            routes_end[0] = 3;
            expect_process_trace_rejection(
                "process trace route length is invalid",
                hash_trace_fixture
            );
            routes_end[0] = 2;

            route_values[1] = 1;
            expect_process_trace_rejection(
                "process trace routes are not a permutation",
                hash_trace_fixture
            );
            route_values[1] = 2;

            routes_end[0] = 1;
            expect_process_trace_rejection(
                "process trace routes omit a customer",
                hash_trace_fixture
            );
            routes_end[0] = 2;

            transfer_mask[1] = 2;
            expect_process_trace_rejection(
                "process trace transfer mask is not boolean",
                hash_trace_fixture
            );
            transfer_mask[1] = 0;

            trace_fixture.feasible = 2;
            expect_process_trace_rejection(
                "process trace feasible flag is not boolean",
                hash_trace_fixture
            );
            trace_fixture.feasible = 1;

            expect_process_trace_rejection(
                "process trace generation is null",
                []() { (void)process_trace_entry(nullptr, 3, 1, 1); }
            );
            Individual* duplicate_population[] = {
                &trace_fixture,
                &trace_fixture,
            };
            Generation duplicate_best{
                1,
                duplicate_population,
                &trace_fixture,
                2,
            };
            NP = 2;
            expect_process_trace_rejection(
                "process trace best appears in multiple slots",
                [&duplicate_best]() {
                    (void)process_trace_entry(&duplicate_best, 3, 1, 1);
                }
            );
            std::cout << "SCVRP_LEGACY_RUNNER_SELF_TEST_V1\n";
            return 0;
        }
        if (argc != 1) {
            throw std::runtime_error("unsupported command-line arguments");
        }
        const Input input = read_input();
        NP = 3 * input.customers;
        Customer* customers = make_customers(input);
        int** distances = make_distances(input);
        Individual* fixed_routes = make_fixed_routes(input);
        const int transfer_cost_once = static_cast<int>(
            calculate_transfer_cost(distances, input.customers)
        );

        srand(input.seed);
        Generation* generation = initial_population(
            distances,
            customers,
            input.customers,
            input.vehicles,
            input.capacity,
            fixed_routes,
            transfer_cost_once
        );
        if (input.probe_new_generation) {
            std::cout
                << "{\"protocol\":\"SCVRP_LEGACY_GENERATION_PROBE_V2\""
                << ",\"seed\":" << input.seed
                << ",\"temperature_hex\":\""
                << double_hex(input.start_temperature) << "\""
                << ",\"temperature_schedule_hex\":[";
            double scheduled_temperature = input.start_temperature;
            for (int transition = 0; transition < input.limit; ++transition) {
                if (transition != 0) {
                    std::cout << ',';
                }
                std::cout << '\"' << double_hex(scheduled_temperature) << '\"';
                if ((transition + 1) % input.iterations_per_temperature == 0) {
                    scheduled_temperature *= input.cooling_rate;
                }
            }
            std::cout
                << "]"
                << ",\"trace\":[";
            write_generation_defined_state(
                generation,
                input.customers,
                fixed_routes->vehicles_num_K
            );
            double temperature = input.start_temperature;
            for (int transition = 0; transition < input.limit; ++transition) {
                Generation* next = new_generation(
                    generation,
                    distances,
                    customers,
                    input.customers,
                    input.vehicles,
                    input.capacity,
                    RAND_1_EXP,
                    temperature,
                    fixed_routes,
                    transfer_cost_once
                );
                generation = generation_free(generation, input.vehicles);
                generation = next;
                generation_clear_cloned_flags(generation);
                std::cout << ',';
                write_generation_defined_state(
                    generation,
                    input.customers,
                    fixed_routes->vehicles_num_K
                );
                if ((transition + 1) % input.iterations_per_temperature == 0) {
                    temperature *= input.cooling_rate;
                }
            }
            std::cout << "]}\n";

            generation = generation_free(generation, input.vehicles);
            distances = distances_matrix_free(distances, input.customers);
            free_fixed_routes(fixed_routes);
            delete[] customers;
            return 0;
        }
        if (input.probe_target >= 0) {
            if (input.probe_target >= NP) {
                throw std::runtime_error("probe_target is outside the population");
            }
            const uint32_t initial_rng_state = scvrp_msvc_rand_state();
            const uint64_t initial_rng_draw_count = scvrp_msvc_rand_draw_count();
            Individual* mutant = mutation(
                generation,
                input.probe_target,
                input.customers,
                input.vehicles,
                MUTATION_RAND,
                fixed_routes
            );
            const uint32_t mutation_rng_state = scvrp_msvc_rand_state();
            const uint64_t mutation_rng_draw_count = scvrp_msvc_rand_draw_count();
            Individual* trial = crossover(
                generation->individuals[input.probe_target],
                mutant,
                input.customers,
                input.vehicles,
                CROSSOVER_EXP,
                fixed_routes
            );
            const uint32_t crossover_rng_state = scvrp_msvc_rand_state();
            const uint64_t crossover_rng_draw_count = scvrp_msvc_rand_draw_count();

            std::cout << "{\"protocol\":\"SCVRP_LEGACY_PROBE_V8\""
                      << ",\"seed\":" << input.seed
                      << ",\"target_index\":" << input.probe_target
                      << ",\"rng_after_initial\":";
            write_rng_fingerprint(initial_rng_state, initial_rng_draw_count);
            std::cout << ",\"target\":";
            write_individual_genome(
                generation->individuals[input.probe_target],
                input.customers
            );
            std::cout << ",\"rng_after_mutation\":";
            write_rng_fingerprint(mutation_rng_state, mutation_rng_draw_count);
            std::cout << ",\"mutant\":";
            write_individual_genome(mutant, input.customers);
            std::cout << ",\"rng_after_crossover\":";
            write_rng_fingerprint(crossover_rng_state, crossover_rng_draw_count);
            std::cout << ",\"trial\":";
            write_individual_genome(trial, input.customers);

            // The crossover clone intentionally has undefined evaluation
            // arrays.  Match new_generation by reevaluating before the probe
            // observes any capacities or scalar evaluation fields.
            individual_reevaluate(
                trial,
                input.capacity,
                input.vehicles,
                distances,
                customers,
                fixed_routes,
                transfer_cost_once
            );
            const uint32_t reevaluate_rng_state = scvrp_msvc_rand_state();
            const uint64_t reevaluate_rng_draw_count = scvrp_msvc_rand_draw_count();
            std::cout << ",\"rng_after_reevaluate\":";
            write_rng_fingerprint(reevaluate_rng_state, reevaluate_rng_draw_count);
            std::cout << ",\"trial_reevaluated\":";
            write_individual_defined_state(
                trial,
                input.customers,
                fixed_routes->vehicles_num_K
            );

            std::cout << ",\"drop_infeasible_probe\":";
            if (trial->feasible) {
                // Calling the archive on a feasible state would loop forever
                // while searching for a route with negative free capacity.
                std::cout << "null";
            } else {
                Individual* drop_result = make_defined_state_clone(
                    trial,
                    input.customers,
                    fixed_routes
                );
                const int return_value = drop_one_point_infeasible(
                    drop_result,
                    distances,
                    customers,
                    input.vehicles,
                    input.customers
                );
                const uint32_t drop_rng_state = scvrp_msvc_rand_state();
                const uint64_t drop_rng_draw_count =
                    scvrp_msvc_rand_draw_count();
                std::cout << "{\"return_value\":" << return_value
                          << ",\"rng\":";
                write_rng_fingerprint(drop_rng_state, drop_rng_draw_count);
                std::cout << ",\"state\":";
                write_individual_defined_state(
                    drop_result,
                    input.customers,
                    fixed_routes->vehicles_num_K
                );
                std::cout << '}';
                drop_result = individual_free(drop_result, input.vehicles);

                restore_probe_rng_prefix(input.seed, reevaluate_rng_draw_count);
                if (scvrp_msvc_rand_state() != reevaluate_rng_state ||
                    scvrp_msvc_rand_draw_count() != reevaluate_rng_draw_count) {
                    throw std::runtime_error("failed to restore isolated probe RNG");
                }
            }

            std::cout << ",\"local_search_probe\":";
            if (!input.probe_local_search) {
                std::cout << "null";
            } else {
                // Exercise the complete archived orchestration on its own
                // defined clone and logical RNG branch.  Replaying the
                // pre-probe prefix below keeps every existing probe and
                // production flow observationally unchanged.
                Individual* local_search_result = make_defined_state_clone(
                    trial,
                    input.customers,
                    fixed_routes
                );
                local_search(
                    local_search_result,
                    distances,
                    customers,
                    input.vehicles,
                    fixed_routes,
                    transfer_cost_once,
                    input.capacity,
                    input.customers
                );
                const uint32_t local_search_rng_state = scvrp_msvc_rand_state();
                const uint64_t local_search_rng_draw_count =
                    scvrp_msvc_rand_draw_count();
                std::cout << "{\"rng\":";
                write_rng_fingerprint(
                    local_search_rng_state,
                    local_search_rng_draw_count
                );
                std::cout << ",\"state\":";
                write_individual_defined_state(
                    local_search_result,
                    input.customers,
                    fixed_routes->vehicles_num_K
                );
                std::cout << '}';
                local_search_result = individual_free(
                    local_search_result,
                    input.vehicles
                );

                restore_probe_rng_prefix(input.seed, reevaluate_rng_draw_count);
                if (scvrp_msvc_rand_state() != reevaluate_rng_state ||
                    scvrp_msvc_rand_draw_count() != reevaluate_rng_draw_count) {
                    throw std::runtime_error("failed to restore isolated probe RNG");
                }
            }

            std::cout << ",\"sa_acceptance_probe\":";
            if (input.probe_sa_cases.empty()) {
                std::cout << "null";
            } else {
                std::cout << '[';
                for (size_t index = 0; index < input.probe_sa_cases.size(); ++index) {
                    if (index != 0) {
                        std::cout << ',';
                    }
                    const SAAcceptanceCase& probe_case =
                        input.probe_sa_cases[index];
                    srand(probe_case.rng_seed);
                    const int raw_rand = rand();
                    const double rand_value = raw_rand / (double)RAND_MAX;
                    const double exponent =
                        (probe_case.target_cost - probe_case.trial_cost) /
                        probe_case.temperature;
                    const double probability = std::exp(exponent);
                    const bool accepted =
                        probe_case.trial_cost < probe_case.target_cost ||
                        std::exp(
                            (probe_case.target_cost - probe_case.trial_cost) /
                            probe_case.temperature
                        ) > rand_value;
                    const uint32_t case_rng_state = scvrp_msvc_rand_state();
                    const uint64_t case_rng_draw_count =
                        scvrp_msvc_rand_draw_count();

                    std::cout << "{\"rng_seed\":" << probe_case.rng_seed
                              << ",\"target_cost\":" << probe_case.target_cost
                              << ",\"trial_cost\":" << probe_case.trial_cost
                              << ",\"temperature_hex\":\""
                              << double_hex(probe_case.temperature)
                              << "\",\"raw_rand\":" << raw_rand
                              << ",\"rand_value_hex\":\""
                              << double_hex(rand_value)
                              << "\",\"exponent_hex\":\""
                              << double_hex(exponent)
                              << "\",\"probability_hex\":\""
                              << double_hex(probability)
                              << "\",\"accepted\":"
                              << (accepted ? "true" : "false")
                              << ",\"rng\":";
                    write_rng_fingerprint(case_rng_state, case_rng_draw_count);
                    std::cout << '}';
                }
                std::cout << ']';

                restore_probe_rng_prefix(input.seed, reevaluate_rng_draw_count);
                if (scvrp_msvc_rand_state() != reevaluate_rng_state ||
                    scvrp_msvc_rand_draw_count() != reevaluate_rng_draw_count) {
                    throw std::runtime_error("failed to restore isolated probe RNG");
                }
            }

            // two_swap mutates its argument in place.  Keep this test-only
            // oracle branch isolated from both the source trial and every
            // other local-search probe.
            Individual* two_swap_result = make_defined_state_clone(
                trial,
                input.customers,
                fixed_routes
            );
            two_swap(
                two_swap_result,
                distances,
                customers,
                input.vehicles,
                input.customers
            );
            const uint32_t two_swap_rng_state = scvrp_msvc_rand_state();
            const uint64_t two_swap_rng_draw_count = scvrp_msvc_rand_draw_count();
            std::cout << ",\"two_swap_probe\":{\"rng\":";
            write_rng_fingerprint(two_swap_rng_state, two_swap_rng_draw_count);
            std::cout << ",\"state\":";
            write_individual_defined_state(
                two_swap_result,
                input.customers,
                fixed_routes->vehicles_num_K
            );
            std::cout << '}';
            two_swap_result = individual_free(two_swap_result, input.vehicles);

            std::cout << ",\"two_swap_mixed_probe\":";
            if (input.probe_two_swap_transfer_customer == -1) {
                std::cout << "null";
            } else {
                Individual* mixed = make_defined_state_clone(
                    trial,
                    input.customers,
                    fixed_routes
                );
                mixed->Customer_Transfer[
                    input.probe_two_swap_transfer_customer
                ] = 1;
                individual_reevaluate(
                    mixed,
                    input.capacity,
                    input.vehicles,
                    distances,
                    customers,
                    fixed_routes,
                    transfer_cost_once
                );
                std::cout << "{\"transfer_customer\":"
                          << input.probe_two_swap_transfer_customer
                          << ",\"baseline\":";
                write_individual_defined_state(
                    mixed,
                    input.customers,
                    fixed_routes->vehicles_num_K
                );

                two_swap(
                    mixed,
                    distances,
                    customers,
                    input.vehicles,
                    input.customers
                );
                const uint32_t mixed_rng_state = scvrp_msvc_rand_state();
                const uint64_t mixed_rng_draw_count = scvrp_msvc_rand_draw_count();
                std::cout << ",\"rng\":";
                write_rng_fingerprint(mixed_rng_state, mixed_rng_draw_count);
                std::cout << ",\"state\":";
                write_individual_defined_state(
                    mixed,
                    input.customers,
                    fixed_routes->vehicles_num_K
                );
                std::cout << '}';
                mixed = individual_free(mixed, input.vehicles);
            }

            // strong_drop_one_point mutates route layout, positions, capacities,
            // cost, and possibly feasibility.  Always start from a full deep
            // copy of the post-crossover reevaluation so this archived oracle
            // cannot affect two-swap, reinsertion, transfer, or production flow.
            Individual* strong_drop_result = make_defined_state_clone(
                trial,
                input.customers,
                fixed_routes
            );
            strong_drop_one_point(
                strong_drop_result,
                distances,
                customers,
                input.vehicles,
                input.customers
            );
            const uint32_t strong_drop_rng_state = scvrp_msvc_rand_state();
            const uint64_t strong_drop_rng_draw_count =
                scvrp_msvc_rand_draw_count();
            std::cout << ",\"strong_drop_probe\":{\"rng\":";
            write_rng_fingerprint(
                strong_drop_rng_state,
                strong_drop_rng_draw_count
            );
            std::cout << ",\"state\":";
            write_individual_defined_state(
                strong_drop_result,
                input.customers,
                fixed_routes->vehicles_num_K
            );
            std::cout << '}';
            strong_drop_result = individual_free(
                strong_drop_result,
                input.vehicles
            );

            // A single optional customer keeps mixed-transfer coverage bounded
            // while exercising strong-drop's zero-load branch in isolation.
            std::cout << ",\"strong_drop_mixed_probe\":";
            if (input.probe_strong_drop_transfer_customer == -1) {
                std::cout << "null";
            } else {
                Individual* mixed = make_defined_state_clone(
                    trial,
                    input.customers,
                    fixed_routes
                );
                mixed->Customer_Transfer[
                    input.probe_strong_drop_transfer_customer
                ] = 1;
                individual_reevaluate(
                    mixed,
                    input.capacity,
                    input.vehicles,
                    distances,
                    customers,
                    fixed_routes,
                    transfer_cost_once
                );
                std::cout << "{\"transfer_customer\":"
                          << input.probe_strong_drop_transfer_customer
                          << ",\"baseline\":";
                write_individual_defined_state(
                    mixed,
                    input.customers,
                    fixed_routes->vehicles_num_K
                );

                strong_drop_one_point(
                    mixed,
                    distances,
                    customers,
                    input.vehicles,
                    input.customers
                );
                const uint32_t mixed_rng_state = scvrp_msvc_rand_state();
                const uint64_t mixed_rng_draw_count = scvrp_msvc_rand_draw_count();
                std::cout << ",\"rng\":";
                write_rng_fingerprint(mixed_rng_state, mixed_rng_draw_count);
                std::cout << ",\"state\":";
                write_individual_defined_state(
                    mixed,
                    input.customers,
                    fixed_routes->vehicles_num_K
                );
                std::cout << '}';
                mixed = individual_free(mixed, input.vehicles);
            }

            std::cout << ",\"reinsertion_probe\":";
            if (input.probe_reinsert_customer == -1) {
                std::cout << "null";
            } else {
                const int customer = input.probe_reinsert_customer;
                const int new_route = input.probe_reinsert_new_route;
                if (trial->positions[0][customer] == new_route) {
                    throw std::runtime_error(
                        "reinsertion probe new route must differ from the source route"
                    );
                }
                const int load = trial->Customer_Transfer[customer] == 1
                    ? 0
                    : customers[customer].demand;

                Individual* if_improves = make_defined_state_clone(
                    trial,
                    input.customers,
                    fixed_routes
                );
                const int improved =
                    reinsert_customer_best_position_in_another_route_if_improves(
                        if_improves,
                        distances,
                        customer,
                        load,
                        new_route,
                        input.customers
                    );
                const uint32_t if_improves_rng_state = scvrp_msvc_rand_state();
                const uint64_t if_improves_rng_draw_count =
                    scvrp_msvc_rand_draw_count();

                Individual* forced = make_defined_state_clone(
                    trial,
                    input.customers,
                    fixed_routes
                );
                reinsert_customer_best_position_in_another_route(
                    forced,
                    distances,
                    customer,
                    load,
                    new_route,
                    input.customers
                );
                const uint32_t forced_rng_state = scvrp_msvc_rand_state();
                const uint64_t forced_rng_draw_count = scvrp_msvc_rand_draw_count();

                std::cout << "{\"customer\":" << customer
                          << ",\"new_route\":" << new_route
                          << ",\"if_improves\":{\"applied\":"
                          << (improved ? "true" : "false")
                          << ",\"rng\":";
                write_rng_fingerprint(
                    if_improves_rng_state,
                    if_improves_rng_draw_count
                );
                std::cout << ",\"state\":";
                write_individual_defined_state(
                    if_improves,
                    input.customers,
                    fixed_routes->vehicles_num_K
                );
                std::cout << "},\"forced\":{\"rng\":";
                write_rng_fingerprint(forced_rng_state, forced_rng_draw_count);
                std::cout << ",\"state\":";
                write_individual_defined_state(
                    forced,
                    input.customers,
                    fixed_routes->vehicles_num_K
                );
                std::cout << "}}";

                if_improves = individual_free(if_improves, input.vehicles);
                forced = individual_free(forced, input.vehicles);
            }

            calculate_customer_turnto_transfer(
                distances,
                trial,
                input.customers,
                customers,
                fixed_routes,
                transfer_cost_once,
                input.capacity
            );
            const uint32_t transfer_rng_state = scvrp_msvc_rand_state();
            const uint64_t transfer_rng_draw_count = scvrp_msvc_rand_draw_count();
            std::cout << ",\"rng_after_turn_to_transfer\":";
            write_rng_fingerprint(transfer_rng_state, transfer_rng_draw_count);
            std::cout << ",\"after_turn_to_transfer\":";
            write_individual_defined_state(
                trial,
                input.customers,
                fixed_routes->vehicles_num_K
            );

            calculate_customer_turnto_notransfer(
                distances,
                trial,
                input.customers,
                customers,
                fixed_routes,
                transfer_cost_once,
                input.capacity
            );
            const uint32_t no_transfer_rng_state = scvrp_msvc_rand_state();
            const uint64_t no_transfer_rng_draw_count = scvrp_msvc_rand_draw_count();
            std::cout << ",\"rng_after_turn_to_no_transfer\":";
            write_rng_fingerprint(no_transfer_rng_state, no_transfer_rng_draw_count);
            std::cout << ",\"after_turn_to_no_transfer\":";
            write_individual_defined_state(
                trial,
                input.customers,
                fixed_routes->vehicles_num_K
            );
            std::cout << "}\n";

            mutant = individual_free(mutant, input.vehicles);
            trial = individual_free(trial, input.vehicles);
            generation = generation_free(generation, input.vehicles);
            distances = distances_matrix_free(distances, input.customers);
            free_fixed_routes(fixed_routes);
            delete[] customers;
            return 0;
        }
        std::vector<Snapshot> trace;
        if (input.trace) {
            trace.push_back(snapshot(generation, input.customers));
        }
        std::vector<ProcessTraceEntry> process_trace;
        if (input.process_trace) {
            process_trace.push_back(
                process_trace_entry(
                    generation,
                    input.customers,
                    input.vehicles,
                    fixed_routes->vehicles_num_K
                )
            );
        }

        int transitions = 0;
        int temperature_stagnation = 0;
        int last_progress_cost = generation->best_solution->cost;
        double temperature = input.start_temperature;
        bool stop = false;
        bool safety_limit_reached = false;
        do {
            int iterations_this_level = input.iterations_per_temperature;
            if (input.termination == "fixed_iterations") {
                const int remaining = input.limit - transitions;
                if (remaining <= 0) {
                    break;
                }
                if (iterations_this_level > remaining) {
                    iterations_this_level = remaining;
                }
            }

            for (int iteration = 0; iteration < iterations_this_level; ++iteration) {
                Generation* next = new_generation(
                    generation,
                    distances,
                    customers,
                    input.customers,
                    input.vehicles,
                    input.capacity,
                    RAND_1_EXP,
                    temperature,
                    fixed_routes,
                    transfer_cost_once
                );
                generation = generation_free(generation, input.vehicles);
                generation = next;
                generation_clear_cloned_flags(generation);
                ++transitions;
                if (input.trace) {
                    trace.push_back(snapshot(generation, input.customers));
                }
                if (input.process_trace) {
                    process_trace.push_back(
                        process_trace_entry(
                            generation,
                            input.customers,
                            input.vehicles,
                            fixed_routes->vehicles_num_K
                        )
                    );
                }
                const bool fixed_target_reached =
                    input.termination == "fixed_iterations" && transitions >= input.limit;
                if (transitions >= input.max_transitions && !fixed_target_reached) {
                    safety_limit_reached = true;
                    break;
                }
            }

            if (!safety_limit_reached &&
                iterations_this_level == input.iterations_per_temperature) {
                temperature *= input.cooling_rate;
                if (last_progress_cost <= generation->best_solution->cost) {
                    ++temperature_stagnation;
                } else {
                    last_progress_cost = generation->best_solution->cost;
                    temperature_stagnation = 0;
                }
            }

            if (safety_limit_reached) {
                stop = true;
            } else if (input.termination == "fixed_iterations") {
                stop = transitions >= input.limit;
            } else {
                stop = temperature_stagnation > input.limit;
            }
        } while (!stop);

        const Snapshot result = snapshot(generation, input.customers);
        std::cout << "{\"protocol\":\""
                  << (input.process_trace
                          ? "SCVRP_LEGACY_DEEP_TRACE_V1"
                          : "SCVRP_LEGACY_RESULT_V1")
                  << "\""
                  << ",\"seed\":" << input.seed
                  << ",\"termination\":\"" << input.termination << "\""
                  << ",\"stop_cause\":\""
                  << (safety_limit_reached ? "max_transitions" : input.termination)
                  << "\""
                  << ",\"generation_count\":" << result.generation
                  << ",\"transition_count\":" << transitions
                  << ",\"temperature_stagnation\":" << temperature_stagnation
                  << ",\"final_temperature_hex\":\"" << std::hexfloat << temperature
                  << std::defaultfloat << "\""
                  << ",\"rng_state\":" << scvrp_msvc_rand_state()
                  << ",\"rng_draw_count\":" << scvrp_msvc_rand_draw_count()
                  << ",\"result\":";
        write_snapshot(result);
        std::cout << ",\"trace\":[";
        for (size_t index = 0; index < trace.size(); ++index) {
            if (index != 0) {
                std::cout << ',';
            }
            write_snapshot(trace[index]);
        }
        std::cout << ']';
        if (input.process_trace) {
            std::cout
                << ",\"process_trace\":{"
                << "\"schema\":\"SCVRP_FULL_POP_V1\""
                << ",\"trace_schema\":\"SCVRP_FULL_TRACE_V1\""
                << ",\"algorithm\":\"sha256\""
                << ",\"generation_digests\":[";
            for (size_t index = 0; index < process_trace.size(); ++index) {
                if (index != 0) {
                    std::cout << ',';
                }
                std::cout << '\"'
                          << digest_hex(process_trace[index].canonical_digest)
                          << '\"';
            }
            std::cout
                << "]"
                << ",\"generations\":[";
            for (size_t index = 0; index < process_trace.size(); ++index) {
                if (index != 0) {
                    std::cout << ',';
                }
                const ProcessTraceEntry& entry = process_trace[index];
                std::cout
                    << "{\"generation\":" << entry.generation
                    << ",\"canonical_digest\":\""
                    << digest_hex(entry.canonical_digest)
                    << "\",\"rng_state\":" << entry.rng_state
                    << ",\"rng_draw_count\":" << entry.rng_draw_count
                    << '}';
            }
            std::cout
                << "]"
                << ",\"trace_sha256\":\""
                << digest_hex(process_trace_digest(process_trace))
                << "\"}";
        }
        std::cout << "}\n";

        generation = generation_free(generation, input.vehicles);
        distances = distances_matrix_free(distances, input.customers);
        free_fixed_routes(fixed_routes);
        delete[] customers;
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "SCVRP legacy runner error: " << error.what() << '\n';
        return 2;
    }
}
