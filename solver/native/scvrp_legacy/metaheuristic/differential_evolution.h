#ifndef DIFFERENTIAL_EVOLUTION_H
#define DIFFERENTIAL_EVOLUTION_H
#include <stdio.h>
#include "../common/dependences.h"

#define F 0.7
#define CR 0.7
//#define NP 250
#define MAX_GEN 500000
#define PENALTY 100.0

#define PRINT_IN_FILE 1


enum MutationType { MUTATION_RAND, MUTATION_BEST };
enum CrossoverType { CROSSOVER_BIN, CROSSOVER_EXP };
enum DETechnique { RAND_1_BIN, RAND_1_EXP, BEST_1_BIN, BEST_1_EXP };

typedef struct generation Generation;

struct generation{
    int         id;
    Individual  **individuals;
    Individual  *best_solution;
    int         feasible_solutions_num;
};



Generation* generation_init();
            
Generation* initial_population(int** distances, Customer* customers, int customers_num, int vehicles_num, int capacity_max, Individual* Fixed_Route_individual, int transfer_cost_once);

//原始
//Generation* new_generation(Generation* generation, int** distances, Customer* customers, int customers_num, int vehicles_num, int capacity_max, enum DETechnique de_technique);
//TODO:SA
Generation* new_generation(Generation* generation, int** distances, Customer* customers, int customers_num, int vehicles_num, int capacity_max, enum DETechnique de_technique, double temperature, Individual* Fixed_Route_individual, int transfer_cost_once);

Generation* generation_free(Generation* generation, int vehicles_num);


Generation* differential_evolution(int** distances, Customer* customers, int customers_num, int vehicles_num, int capacity_max, int best_solution, enum DETechnique de_technique,FILE* outputtime_file,int time_termination,int max_temp_no_updata, sa sa, char* filename,int seed, Individual* Fixed_Route_individual, int transfer_cost_once);

Individual* mutation(Generation* generation, int target_idx, int customers_num, int vehicles_num, enum MutationType mutation_type, Individual* Fixed_Route_individual);

Individual* crossover(Individual* x1, Individual* mutant, int customers_num, int vehicles_num, enum CrossoverType crossover_type, Individual* Fixed_Route_individual);


Individual* generate_new_mutant(Individual* x1, Individual* x2, Individual* x3, int vehicles_num, int customers_num, Individual* Fixed_Route_individual);

//generate new mutant continuous


void generation_clear_cloned_flags(Generation* generation);


#endif /*DIFFERENTIAL_EVOLUTION_H*/
