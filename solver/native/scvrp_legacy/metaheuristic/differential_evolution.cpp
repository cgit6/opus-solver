#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>
#include <time.h>
#include <math.h>

#include "../common/local_search.h"
#include "../common/dependences.h"
#include "../common/io_tools.h"

#include "../metaheuristic/differential_evolution.h"

//double F, CR;
extern int NP;
static int id = 1;
int de_debug = 0;
Generation* generation_init() {
    //因為static所以初始化也只會發生在第一次調用時，下方有id++所以之後再調用時id就會是已經加一過的值，所以每一個世代初始都會是正確的id
    //static int id = 1;
    
    Generation *generation = (Generation*) malloc (sizeof(Generation));
    generation->individuals = (Individual**) malloc (NP * sizeof(Individual*));

/*  int i = 0;
    while (i < NP) {
        generation->individuals[i] = NULL;
        i++;
    }
*/
    generation->id = id;
    generation->best_solution = NULL;
    generation->feasible_solutions_num = 0;
    id++;
    
    return generation;
}

Generation* initial_population(int** distances, Customer* customers, int customers_num, int vehicles_num, int capacity_max, Individual* Fixed_Route_individual, int transfer_cost_once) {
    Generation *generation = generation_init();
    Individual *individual;
    
    //TODO: remove and include in loop
    int select = rand() % 2;
    //執行初始化個體(包含計算適應值)
            //以下兩種有兩個差異
                //1.計劃路徑的方向
                //2.插入未分配客戶的策略
    if (select == 1) {
        //1.從第一條路徑開始，並向下計劃路徑，即從0開始，直到vehicles_num(++)
        //2.如果有些客戶還未被分配到某條路徑，他們將被加入到最後一條路徑。此處使用 routes_planned_cnt--
        individual = individual_generate_top_to_down(distances, customers, customers_num, capacity_max, vehicles_num,  Fixed_Route_individual, transfer_cost_once);
    } else {
        //1.從最後一條路徑開始，並向上計劃路徑，即從vehicles_num - 1開始，直到0(--)
        //2.如果有些客戶還未被分配到某條路徑，他們將被加入到第一條路徑。此處使用 routes_planned_cnt++
        individual = individual_generate_down_to_top(distances, customers, customers_num, capacity_max, vehicles_num, Fixed_Route_individual, transfer_cost_once);
    }
    /*測試當前程式是否能正確計算cost和capacities給GUROBI解答*/
    /*individual->routes[0][0]=4;individual->routes[0][1]=12; individual->routes[0][2] = 1;
    individual->routes[1][0]=14;individual->routes[1][1]=9; individual->routes[1][2] = 13; individual->routes[1][3] = 8; individual->routes[1][4] = 2;
    individual->routes[2][0]=3;individual->routes[2][1]=5; individual->routes[2][2] = 6; individual->routes[2][3] = 7; individual->routes[2][4] = 10;
    individual->routes[3][0]=11;individual->routes[3][1]=15;*/
    
    /*測試當前程式是否能正確計算cost和capacities給GUROBI解答*/
    generation->individuals[0] = individual;
    //更新當前最佳解
    generation->best_solution = individual;
    //如果個體可行(重量符合)
    if (individual->feasible) {
        //更新個體可行數量
        generation->feasible_solutions_num++;
    }
    
    int i = 1;
    //執行NP次產生NP-1個個體(從1開始)個體0在上方
    while (i < NP) {
        select = rand() % 2;
        //執行初始化個體(包含計算適應值)
            //以下兩種有兩個差異
                //1.計劃路徑的方向
                //2.插入未分配客戶的策略
        if (select == 1) {
            //1.從第一條路徑開始，並向下計劃路徑，即從0開始，直到vehicles_num(++)
            //2.如果有些客戶還未被分配到某條路徑，他們將被加入到最後一條路徑。此處使用 routes_planned_cnt--
            individual = individual_generate_top_to_down(distances, customers, customers_num, capacity_max, vehicles_num, Fixed_Route_individual,transfer_cost_once);
        } else {
            //1.從最後一條路徑開始，並向上計劃路徑，即從vehicles_num - 1開始，直到0(--)
            //2.如果有些客戶還未被分配到某條路徑，他們將被加入到第一條路徑。此處使用 routes_planned_cnt++
            individual = individual_generate_down_to_top(distances, customers, customers_num, capacity_max, vehicles_num, Fixed_Route_individual, transfer_cost_once);
        }
        //放進individuals[]裡
        generation->individuals[i] = individual;
        //如果此個體可行(重量可行)
        if (individual->feasible) {
            //更新個體可行數量
            generation->feasible_solutions_num++;
            //是否有比當前最佳解更好
            if (individual->cost < generation->best_solution->cost) {
                //有=>更新當前最佳解
                generation->best_solution = individual;
            }
        }
        //更新i(準備產生下一個個體)
        i++;
    }
    return generation;
}

void generation_clear_cloned_flags(Generation* generation) {
    for (int i = 0; i < NP; i++) {
        if (generation->individuals[i]->cloned) {
            generation->individuals[i]->cloned = 0;
        }
    }

    return;
}

//原始
//Generation* new_generation(Generation* generation, int** distances, Customer* customers, int customers_num, int vehicles_num, int capacity_max, enum DETechnique de_technique) {
//TODO:SA
Generation* new_generation(Generation* generation, int** distances, Customer* customers, int customers_num, int vehicles_num, int capacity_max, enum DETechnique de_technique,double temperature, Individual* Fixed_Route_individual,int transfer_cost_once) {
    Individual  *mutant = NULL,
                *trial = NULL,
                *target = NULL;

    enum CrossoverType crossover_type;
    enum MutationType mutation_type;

    //根據de_technique(DE策略)會有對應不同
    switch (de_technique) {
        case RAND_1_BIN:
            mutation_type = MUTATION_RAND;
            crossover_type = CROSSOVER_BIN;
            break;

        case RAND_1_EXP:
            mutation_type = MUTATION_RAND;
            crossover_type = CROSSOVER_EXP;
            break;

        case BEST_1_BIN:
            mutation_type = MUTATION_BEST;
            crossover_type = CROSSOVER_BIN;
            break;

        case BEST_1_EXP:
            mutation_type = MUTATION_BEST;
            crossover_type = CROSSOVER_EXP;
            break;

        default:
            printf("[ERROR]: Bad DE technique.\n");
            exit(1);
    }
    
    //初始一個新世代
    Generation* generation2 = generation_init();
    //新世代的最佳解會是上一世代的最佳解
    generation2->best_solution = generation->best_solution;
    //如果複製完不是NULL，表示有成功，表示該個體是否已被克隆標記要改成是(1)
    if (generation2->best_solution != NULL) {
        generation2->best_solution->cloned = 1;
    }

    int generation2_has_best_solution_generation1 = 0;

    int target_idx = 0;
    if (de_debug==1) { 
        printf("new_generation偵測點0\n"); 
    }
    //執行NP次(從0開始)
    while (target_idx < NP) {
        //用上一個世代個體突變成當前世代
        mutant = mutation(generation, target_idx, customers_num, vehicles_num, mutation_type, Fixed_Route_individual);
        //上一個世代第target_idx個個體
        target = generation->individuals[target_idx];
        //用上一個世代個體交配成當前世代
        trial = crossover(target, mutant, customers_num, vehicles_num, crossover_type, Fixed_Route_individual);
        
        mutant = individual_free(mutant, vehicles_num);
        //更新個體資訊
        //printf("\nTest Start\n");
        //individual_print(trial, trial->vehicles_num_K);
        individual_reevaluate(trial, capacity_max, vehicles_num, distances, customers, Fixed_Route_individual,transfer_cost_once);
        //printf("Stop\n");
        //getchar();
        //printf("LS前cost=%d  ",trial->cost);
        local_search(trial, distances, customers, vehicles_num, Fixed_Route_individual, transfer_cost_once, capacity_max,customers_num);
        //printf("LS後cost=%d\n", trial->cost);
        //individual_print(trial, trial->vehicles_num_K);
        individual_reevaluate(trial, capacity_max, vehicles_num, distances, customers, Fixed_Route_individual, transfer_cost_once);
        //getchar();
        //擾動完的適應值優於(小於)上一代適應值
            //TODO:SA
        //原始
        /*if (trial->cost < target->cost) {*/
        /*TODO:SA*/
        double rand_val = (rand() / (double)RAND_MAX);
        double delta_exp = exp((target->cost - trial->cost) / temperature);
        if (trial->cost < target->cost || exp((target->cost - trial->cost) / temperature) >rand_val) {
            //驗證是否觸發SA
            //if(trial->cost>=target->cost && exp((target->cost - trial->cost) / temperature) > rand_val) {
            //printf("世代=%d   ",generation2->id);
            //printf("個體=%d   \n",target_idx);
            //printf("target->cost=%d    ",target->cost);
            //printf("trial->cost=%d    \n",trial->cost);
            //printf("temperature=%f    \n",temperature);
            //printf("觸發SA   機率為=%f \n", exp((target->cost - trial->cost) / temperature));
            //printf("delta_exp= %f\n", delta_exp);
            ////getchar();
            //}
        /*TODO:SA*/
            //可行
            if (trial->feasible) {
                generation2->feasible_solutions_num++;
                if (generation2->best_solution != NULL) {
                    //判斷此適應值有無優於當前最佳解
                        //有=>取代
                    if (trial->cost < generation2->best_solution->cost) {
                        if (generation2->best_solution->cloned) {
                            generation2->best_solution->cloned = 0;
                        }
                        generation2->best_solution = trial;
                    }
                }
                generation2->individuals[target_idx] = trial;
                
            //即使一個試驗解的價值表現很好，但如果它不是一個可行的解，那麼它仍然不會被用來替換當前的最佳解
            } else if (target == generation2->best_solution) {
                generation2->individuals[target_idx] = target;
                target->cloned = 1;
                generation2->feasible_solutions_num++;
                generation2_has_best_solution_generation1 = 1;
                trial = individual_free(trial, vehicles_num);
                
            } else {
                generation2->individuals[target_idx] = trial;
            }

        } else {
            generation2->individuals[target_idx] = target;
            target->cloned = 1;
            trial = individual_free(trial, vehicles_num);
            
            if (target->feasible) {
                generation2->feasible_solutions_num++;
                
                if (target == generation2->best_solution) {
                    generation2_has_best_solution_generation1 = 1;
                }
            }
        }
        target_idx++; //TODO: can go to a for
    }

    if (generation2_has_best_solution_generation1)
        generation->best_solution->cloned = 1;
    
        //printf("結束一次世代\n");
       // getchar();
    return generation2;
}

/* If the individual has the cloned flag enabled, means that it was passed to the new generation */
Generation* generation_free(Generation* generation, int vehicles_num) {
    for (int i = 0; i < NP; i++) {
        if (!generation->individuals[i]->cloned) {
            generation->individuals[i] = individual_free(generation->individuals[i], vehicles_num);
        }
    }
    
    free(generation->individuals);
    free(generation);

    return NULL;
}

Individual* generate_new_mutant(Individual* x1, Individual* x2, Individual* x3, int vehicles_num, int customers_num, Individual* Fixed_Route_individual) {//x2沒作用  x1複製成V被改動(Y) x3=>不動(Z)
    int route_target = 0,
        index_target = 0,
        customer_target = 0,
        mutant_route_idx = 0,
        mutant_visitation_idx = 0,
        visitation_index = 0,
        customer_chosen = 0;

    int* customers_possible=new int[customers_num];
    int customers_possible_num = customers_num -1, //TODO: rethink name, i believe its counting with 0 (do/while reasons)
        random_idx = 0;
        
    for (int index = 0; index < customers_num; index++) {
        customers_possible[index] = index;
    }
        
    Individual* mutant = individual_make_hard_clone(x1, customers_num, vehicles_num, Fixed_Route_individual);
    
    
    int pertubed_components_cnt = 0,
        pertubed_components_max = (customers_num/2.0) * F;
    do {
        random_idx = (rand() % customers_possible_num) +1;
        customer_chosen = customers_possible[random_idx];
        
        mutant_route_idx = x3->positions[0][customer_chosen];
        mutant_visitation_idx = x3->positions[1][customer_chosen];
        
        if (mutant->routes_end[mutant_route_idx] < mutant_visitation_idx +1) { /* A rota nao possui a quantidade de customers necessária. Entao a cidade será inserida ao fim da rota. */
            individual_remove_customer(mutant, customer_chosen, 0);

            /* Inserindo a cidade na rota. */
            visitation_index = mutant->routes_end[mutant_route_idx];

            mutant->routes[mutant_route_idx][visitation_index] = customer_chosen;
            mutant->positions[0][customer_chosen] = mutant_route_idx;
            mutant->positions[1][customer_chosen] = visitation_index;
            
            mutant->routes_end[mutant_route_idx]++;

        } else {
            customer_target = mutant->routes[mutant_route_idx][mutant_visitation_idx];
        
            route_target = mutant->positions[0][customer_chosen];
            index_target = mutant->positions[1][customer_chosen];
            
            mutant->routes[mutant_route_idx][mutant_visitation_idx] = customer_chosen;
            mutant->positions[0][customer_chosen] = mutant_route_idx;
            mutant->positions[1][customer_chosen] = mutant_visitation_idx;
            
            mutant->routes[route_target][index_target] = customer_target;
            mutant->positions[0][customer_target] = route_target;
            mutant->positions[1][customer_target] = index_target;
        }
        
        while (random_idx < customers_possible_num -1) {
            customers_possible[random_idx] = customers_possible[random_idx +1];
            random_idx++;
        } 
        customers_possible_num--;
        
        pertubed_components_cnt++;
    } while (pertubed_components_cnt < pertubed_components_max);
    delete customers_possible;
    return mutant;
}

// TODO: use enum
/* mutation_type = 0 o individual target_idx é a melhor solution da populacao.
 * mutation_type = 1 o individual target_idx é aleatório.
 */
Individual* mutation(Generation* generation, int target_idx, int customers_num, int vehicles_num, enum MutationType mutation_type, Individual* Fixed_Route_individual) {
    int r1 = rand() % NP;
    int r2 = rand() % NP;
    int r3 = rand() % NP;

    while (r2 == target_idx) r2 = rand() % NP;
    
    while (r3 == target_idx || r3 == r2) r3 = rand() % NP;

    if (mutation_type == MUTATION_BEST && generation->best_solution != NULL) {
        return generate_new_mutant(generation->best_solution, generation->individuals[r2], generation->individuals[r3], vehicles_num, customers_num, Fixed_Route_individual);
    }
    

    while (r1 == target_idx || r1 == r2 || r1 == r3) r1 = rand() % NP;

    return generate_new_mutant(generation->individuals[r1], generation->individuals[r2], generation->individuals[r3], vehicles_num, customers_num, Fixed_Route_individual);
}

/* A cidade perturbada é a cidade da posicao antiga do individual, que será substituida pela cidade mutant. */
Individual* crossover(Individual* x1, Individual* mutant, int customers_num, int vehicles_num, enum CrossoverType crossover_type, Individual* Fixed_Route_individual) {
    double random = 0.;
    
    int index = 0,
        trial_idx = 0,
        trial_route = 0,
        mutant_idx = 0,
        mutant_route_idx = 0,
        customer_target = 0;

    /* First permutation happens without evaluating CR */
    int j_rand_route = rand() % vehicles_num;
    while (mutant->routes_end[j_rand_route] == 0) {
        if (j_rand_route < vehicles_num -1) { /* Not necessary if all routes have a customer */
            j_rand_route++; 
        } else {
            j_rand_route = 0;
        }
    }
    int j_rand_component = rand() % mutant->routes_end[j_rand_route];
    
    /* A closed customer is a customer that was already perturbed. It is used to not make multiple swaps with same customer */
    int* customers_closed=new int[customers_num];
    memset(customers_closed, 0, customers_num*sizeof(int));
    customers_closed[0] = 1;
    
    Individual* trial = individual_make_hard_clone(x1, customers_num, vehicles_num, Fixed_Route_individual);

    
    int customer_chosen = mutant->routes[j_rand_route][j_rand_component];
    
    /* Perturbando o individual com a cidade selecionada jrand, para garantir que o indivíduo trial seja diferente do indivíduo target_idx. */
    if (j_rand_component >= trial->routes_end[j_rand_route]) {      
        individual_remove_customer(trial, customer_chosen, 0);
        
        /* Adicionando na posicao j_rand. */
        index = trial->routes_end[j_rand_route];
        
        trial->routes[j_rand_route][index] = customer_chosen;
        trial->positions[0][customer_chosen] = j_rand_route; 
        trial->positions[1][customer_chosen] = index;
        
        trial->routes_end[j_rand_route]++;
        customers_closed[customer_chosen] = 1;
    } else {
        customer_target = trial->routes[j_rand_route][j_rand_component];    
    
        /* Se as customers forem iguais a perturbação não é efetuada. */
        if (customer_chosen == customer_target) { 
            customers_closed[customer_chosen] = 1;
        } else {
        
            mutant_route_idx = trial->positions[0][customer_chosen];
            mutant_idx = trial->positions[1][customer_chosen];
        
            trial->routes[j_rand_route][j_rand_component] = customer_chosen;
            trial->positions[0][customer_chosen] = j_rand_route;
            trial->positions[1][customer_chosen] = j_rand_component;
            customers_closed[customer_chosen] = 1;
            
            trial->routes[mutant_route_idx][mutant_idx] = customer_target;
            trial->positions[0][customer_target] = mutant_route_idx;
            trial->positions[1][customer_target] = mutant_idx;
            customers_closed[customer_target] = 1;
        }
    }
    
    for (int i = 0; i < vehicles_num; i++) {
        for (int j = 0; j < mutant->routes_end[i]; j++) {
            random = (double) rand() / RAND_MAX;
            
            if (random <= CR) {
                customer_chosen = mutant->routes[i][j];
                
                /* Se a cidade não foi fechada a perturbação será feita. */
                if (!customers_closed[customer_chosen]) {
                    if (j >= trial->routes_end[i]) {
                        /* Individual target_idx não possui cidade no mesmo indice da componente selecionada. Então a cidade será adicionada ao final daquela lista. */
                        individual_remove_customer(trial, customer_chosen, 0);
                    
                        /* Adicionando na posicao selecionada. */
                        index = trial->routes_end[i];
                        
                        trial->routes[i][index] = customer_chosen;
                        trial->positions[0][customer_chosen] = i; 
                        trial->positions[1][customer_chosen] = index;
        
                        trial->routes_end[i]++;
                        customers_closed[customer_chosen] = 1;
                    } else {
                        customer_target = trial->routes[i][j];
                        
                        /* Se as customers forem iguais a perturbação não é efetuada. */
                        if (customer_chosen == customer_target) { 
                            customers_closed[customer_chosen] = 1;
                        } else {
                    
                            trial_route = trial->positions[0][customer_target];
                            trial_idx = trial->positions[1][customer_target];
                            mutant_route_idx = trial->positions[0][customer_chosen];
                            mutant_idx = trial->positions[1][customer_chosen];
        
                            trial->routes[trial_route][trial_idx] = customer_chosen;
                            trial->positions[0][customer_chosen] = trial_route;
                            trial->positions[1][customer_chosen] = trial_idx;
                            customers_closed[customer_chosen] = 1;
                            
                            trial->routes[mutant_route_idx][mutant_idx] = customer_target;
                            trial->positions[0][customer_target] = mutant_route_idx;
                            trial->positions[1][customer_target] = mutant_idx;
                            customers_closed[customer_target] = 1;
                        }
                    }
                }
                
            } else if (crossover_type == CROSSOVER_EXP) {
                goto END_CROSSOVER; 
            }
        }
    }
END_CROSSOVER:
    delete customers_closed;

    return trial;
}

Generation* differential_evolution(int** distances, Customer* customers, int customers_num, int vehicles_num, int capacity_max, int best_solution, enum DETechnique de_technique, FILE* outputtime_file,int time_termination,int max_temp_no_updata, sa sa,char* filename,int seed, Individual* Fixed_Route_individual,int transfer_cost_once) {
    clock_t begin_time_d, end_time_d, begin_time, end_time;
    double Total_Time;
    //開始時間
    begin_time = clock();
    begin_time_d = clock();
    double time;
    int last_Progress_cost = 0;//上一次更新cost
    //初始化(initial individuals)
    Generation *generation = initial_population(distances, customers, customers_num, vehicles_num, capacity_max, Fixed_Route_individual, transfer_cost_once),
               *generation_new = NULL;
    
    FILE *file_solution = NULL,
         *file_report = NULL;

    //迭代階段
    int generations_cnt = 1,
        temp_no_updata = 0,//降幾次溫沒有更新
        found_best_solution = 0,
        best_fitness = generation->best_solution->cost;
    last_Progress_cost = best_fitness;
    ///*SA參數*/
    //double startTemp= 8;
    //double endTemp= 0.01;
    //double coolingRate= 0.95;
    //int maxIterations = 105;//內循環次數(同溫度試幾次才可降溫)
    double temperature = sa.startTemp;
    
    //預設是0
        //看是否要輸出檔案或者直接用print即可(世代相關資訊)
    if (PRINT_IN_FILE) {
        char sol[80], rep[80];
        strcpy(sol, filename);
        strcat(sol, "_solution.csv");
        file_solution = fopen(sol, "a");
        strcpy(rep, filename);
        strcat(rep, "_report.txt");
        file_report = fopen(rep, "a");

        printf("\nfilename: ,%s(SA),\n", filename);
        printf("start_temperature= %f,", temperature);
        printf("coolingRate= %f,", sa.coolingRate);
        printf("maxIterations= %d,", sa.maxIterations);
        printf("Temperature No Updatae= %d\n", max_temp_no_updata);

        fprintf(outputtime_file, "start_temperature= %f,", temperature);
        fprintf(outputtime_file, "coolingRate= %f,", sa.coolingRate);
        fprintf(outputtime_file, "maxIterations= %d,", sa.maxIterations);
        fprintf(outputtime_file, "Temperature No Updatae= %d\n", max_temp_no_updata);

        fprintf(file_report, "onctime\n");//runtime執行一次
        //fprintf(file_report, "filename: ,%s(SA),\n", filename);
        //fprintf(file_report, "start_temperature= %f,", temperature);
        //fprintf(file_report, "coolingRate= %f,", sa.coolingRate);
        //fprintf(file_report, "maxIterations= %d,", sa.maxIterations);
        //fprintf(file_report, "Temperature No Updatae= %d\n", max_temp_no_updata);
        fprintf(file_solution, "\nfilename: ,%s(SA),", filename);
        fprintf(file_solution, "random seed=,%d,\n", seed);
        fprintf(file_solution, "start_temperature= %f,", temperature);
        fprintf(file_solution, "coolingRate= %f,", sa.coolingRate);
        fprintf(file_solution, "maxIterations= %d,", sa.maxIterations);
        fprintf(file_solution, "Temperature No Updatae= %d\n", max_temp_no_updata);
        generation_print_report_in_file(file_report, generation);
        fprintf(file_report, "\n");
    } 
    //直接只用print(世代相關資訊)
    else {
        generation_print_report(generation);
        printf("\n");
    }
    

    do {
        //SA內循環
        for (int iterationCount = 0; iterationCount < sa.maxIterations; iterationCount++) {  // 內循環
        //產生新世代
        //原始
        //generation_new = new_generation(generation, distances, customers, customers_num, vehicles_num, capacity_max, de_technique);
        //TODO:SA
            if (de_debug == 1) {
                printf("DE偵錯點0\n");
            }
            generation_new = new_generation(generation, distances, customers, customers_num, vehicles_num, capacity_max, de_technique, temperature, Fixed_Route_individual, transfer_cost_once);
            if (de_debug == 1) {
                printf("成功產生一次世代接下來selection\n");
            }
            //if (best_fitness != generation_new->best_solution->cost) {
            if (best_fitness <= generation_new->best_solution->cost) {
                if (PRINT_IN_FILE) {
                    generation_print_report_in_file(file_report, generation_new);
                   //individual_print_in_file(file_report, generation_new->best_solution, vehicles_num, customers_num);
                    fprintf(file_report, "\n");
                }
                else {
                    generation_print_report(generation_new);
                    printf("\n");
                }

                //best_fitness = generation_new->best_solution->cost;
            }
            else {//比較好更新
                best_fitness = generation_new->best_solution->cost;
                if (PRINT_IN_FILE) {
                    generation_print_report_in_file(file_report, generation_new);
                    //individual_print_in_file(file_report, generation_new->best_solution, vehicles_num, customers_num);
                    fprintf(file_report, "\n");
                    if (de_debug == 1) {
                        generation_print_report(generation_new);
                    }
                }
                else {
                    generation_print_report(generation_new);
                    printf("\n");
                }
            }
            if (de_debug ==1) {
                printf("DE偵錯點一\n"); 
            }
            generation = generation_free(generation, vehicles_num);
            generation = generation_new;
            generations_cnt++;
            if (de_debug == 1) {
                printf("DE偵錯點二\n");
            }
            generation_clear_cloned_flags(generation);

            if (generation->best_solution != NULL && generation->best_solution->cost == best_solution) {
                found_best_solution = 1;
            }
        }
        //迴圈最後更新溫度(用冷卻率)
        temperature *= sa.coolingRate;
        if (last_Progress_cost <= generation->best_solution->cost) {//沒更新要累加
            temp_no_updata++;
        }
        else {
            last_Progress_cost = generation->best_solution->cost;
            temp_no_updata = 0;
        }

        /*SA Debug用*/
        //printf("final_temperature= %f\n", temperature);
        //printf("best_solution=%d\n", generation->best_solution->cost);
        end_time_d = clock();
        time = (end_time_d - begin_time_d) / (float)CLOCKS_PER_SEC;
        //printf("time=%.3f\n", time);
        fprintf(outputtime_file,"temperature= %f,", temperature);
        fprintf(outputtime_file,"best_solution=%d,", generation->best_solution->cost);
        fprintf(outputtime_file,"time=%.3f,\n", time);
    }
    //終止條件(while()=true會繼續執行)
        //1.找到最佳解
        //2.達到最大迭代次數
        //3.溫度達到結束溫度(SA)不用
    //原始 
    /*while (!found_best_solution && generations_cnt < MAX_GEN && time<3600);*/
    while (temp_no_updata <= max_temp_no_updata);
    //TODO:SA(不用)
    //while (!found_best_solution && generations_cnt < MAX_GEN && temperature > endTemp);
   
    

    if (PRINT_IN_FILE) {
        if (generations_cnt == MAX_GEN) {
            generation_print_report_in_file(file_report, generation);
            fprintf(file_report, "\n");
        }
    
        if (generation->best_solution != NULL) {
            individual_print_in_file(file_solution, generation->best_solution, vehicles_num, customers_num);
            individual_print(generation->best_solution, vehicles_num, customers_num);
            /*fprintf(allfinal_output, "%d,", generation->best_solution->cost);
            fprintf(allfinal_output, "%.3f,\n", time);
            fclose(allfinal_output);*/
        } else {
            fprintf(file_solution, "\nDid not find a feasible solution.\n");
        }
        
        printf("    File solution.txt was write on disk.\n");
        
        
    } 
    else {
        if (generations_cnt == MAX_GEN) {
            fprintf(outputtime_file, "已達最大迭代次數,");
            printf("已達最大迭代次數\n");
            generation_print_report(generation);
            printf("\n");
        }
        
        //如果有解=>印出
        if (generation->best_solution != NULL) {
            individual_print(generation->best_solution, vehicles_num, customers_num);
            /*printf("final_temperature= %f\n", temperature);
            printf("final_generation= %d\n",generations_cnt);*/
            fprintf(outputtime_file,"final_generation:, %d,",generations_cnt);
            //如果有找到最佳解(解答)
            if (found_best_solution) {
                fprintf(outputtime_file, "found_best_solution:, Y");
                fprintf(outputtime_file, " %d,", best_solution);
            }
            //沒有就印N
            else {
                fprintf(outputtime_file, "found_best_solution:, N,");
                
            }
            //printf找到的最佳解成本
            fprintf(outputtime_file, "solution_find:,%d,\n", generation->best_solution->cost);
        } else {
            printf("\nDid not find a feasible solution.\n");
        }
    }

    //結束時間
    end_time = clock();
    Total_Time = (end_time - begin_time) / (float)CLOCKS_PER_SEC;
    printf("Total_Time = %ld 毫秒\n", (end_time - begin_time));
    printf("Total_Time = %f 秒\n", Total_Time);
    printf("Total_generation : %d\n", generations_cnt);
    printf("avg once generation= %f 秒",Total_Time/generations_cnt);
    fprintf(outputtime_file, "Total_Time :, %ld, ms,", (end_time - begin_time));
    fprintf(outputtime_file, "Total_Time :, %f, s,", Total_Time);
    fprintf(outputtime_file,"Total_generation :, %d,",generations_cnt);
    fprintf(outputtime_file,"avg once generation=, %f, s\n\n", Total_Time / generations_cnt);

    /*fprintf(file_report, "Total_Time :, %ld, ms,", (end_time - begin_time));
    fprintf(file_report, "Total_Time :, %f, s,", Total_Time);
    fprintf(file_report, "Total_generation :, %d,", generations_cnt);
    fprintf(file_report, "avg once generation=, %f, s\n\n", Total_Time / generations_cnt);*/

    fprintf(file_solution, "Total_Time :, %ld, ms,", (end_time - begin_time));
    fprintf(file_solution, "Total_Time :, %f, s,", Total_Time);
    fprintf(file_solution, "Total_generation :, %d,", generations_cnt);
    fprintf(file_solution, "avg once generation=, %f, s\n\n", Total_Time / generations_cnt);

    fclose(outputtime_file);
    fclose(file_report);
    fclose(file_solution);
    
    id = 1;

    return generation;
}
