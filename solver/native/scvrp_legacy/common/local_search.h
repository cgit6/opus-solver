#ifndef LOCALSEARCH_H
#define LOCALSEARCH_H

#include "dependences.h"
#include"io_tools.h"

/* Local search 
 * - One iteration consists by running the following methods sequentially
 *   2-Swap -> Strong drop one point -> [If solution is infeasible] Drop one point infeasible 
 *   If the iteration gets an improvement, then another iteration is executed.
 */
void local_search(Individual* trial, int** distances, Customer* customers, int vehicles_num, Individual* Fixed_Route_individual,int transfer_cost_once, int capacity_max, int customers_num);


/* Two swap 
 * - classical heuristic
 */
void two_swap(Individual* individual, int** distances, Customer* customers, int vehicles_num,int customers_num);


/* Strong drop one point
 * - proposed method
 */
void strong_drop_one_point(Individual* individual, int** distances, Customer* customers, int vehicles_num,int customers_num);


/* Drop one point infeasible
 * - proposed method
 *
 * @return:
 * - 1: if it turned the individual feasible
 * - 0: otherwise
 */
int drop_one_point_infeasible(Individual* individual, int** distances, Customer* customers, int vehicles_num,int customers_num);


/* Reinsert customer best position in another route
 * - A "customer" is removed from the individual and reinserted in the best position of route "new_route_idx". 
 */
void reinsert_customer_best_position_in_another_route(Individual* individual, int** distances, int customer, int load, int new_route_idx,int customers_num);


/* Reinsert customer best position in another route
 * - A "customer" is removed from the individual and reinserted in the best position of route "new_route_idx" if an improvement can be obtained
 *
 * @ return:
 * - 1: an enhancement was obtained
 * - 0: otherwise
 */
int reinsert_customer_best_position_in_another_route_if_improves(Individual* individual, int** distances, int customer, int load, int new_route_idx,int customers_num);



/*從不轉移變轉移 individual->Customer_Transfer[]=0->1*/
void calculate_customer_turnto_transfer(int** distances, Individual* individual, int customers_num, Customer* customers, Individual* Fixed_Route_individual, int transfer_cost_once, int capacity_max);
/*從轉移變不轉移 individual->Customer_Transfer[]=1->0*/
void calculate_customer_turnto_notransfer(int** distances, Individual* individual, int customers_num, Customer* customers, Individual* Fixed_Route_individual, int transfer_cost_once, int capacity_max);

#endif /* LOCALSEARCH_H */
