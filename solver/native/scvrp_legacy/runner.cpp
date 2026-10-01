#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

#include "common/dependences.h"
#include "metaheuristic/differential_evolution.h"

int NP;

namespace {

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
    int probe_target = -1;
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
    expect("probe_target");
    std::cin >> input.probe_target;

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

void write_rng_fingerprint(uint32_t state, uint64_t draw_count) {
    std::cout << "{\"state\":" << state << ",\"draw_count\":" << draw_count << '}';
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

            std::cout << "{\"protocol\":\"SCVRP_LEGACY_PROBE_V1\""
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
        std::cout << "{\"protocol\":\"SCVRP_LEGACY_RESULT_V1\""
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
        std::cout << "]}\n";

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
