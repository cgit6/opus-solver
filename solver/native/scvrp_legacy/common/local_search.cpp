#include <stdlib.h>
#include <math.h>
#include <string.h>
#include <limits.h>

#include "dependences.h"
#include "local_search.h"

#include "../metaheuristic/differential_evolution.h"

int debug = 0;
/* Determina a customer_preceding e a customer_successor da customer determinada pela component.
 *
 * Variáveis:
 *   - (int)  component, route_end, customer_preceding, customer_successor.
 *   - (int*) route.
 */
//來確定一個特定路由上的前一個客戶
//C語言宏
//#define get_customer_preceding_and_successor(component, route, route_end, customer_preceding, customer_successor) \
//    if (component == 0) { \
//        customer_preceding = 0; \
//        customer_successor = route[1]; \
//    } else if (component == route_end -1) { \
//        customer_preceding = route[component -1]; \
//        customer_successor = 0; \
//    } else{ \
//        customer_preceding = route[component -1]; \
//        customer_successor = route[component +1]; \
//    }

//從宏轉成C++函數
void get_customer_preceding_and_successor(int component, int* route, int route_end, int& customer_preceding, int& customer_successor,Individual* individual) {
    //為路線除去0第一個拜訪點位
    if (component == 0) {
        customer_preceding = 0;
        customer_successor = route[1];
    }
    //路線中除去0最後一個拜訪點位
    else if (component == route_end - 1) {
        customer_preceding = route[component - 1];
        customer_successor = 0;
    }
    else {
        customer_preceding = route[component - 1];
        customer_successor = route[component + 1];
    }
}







//TODO: delete this function? 
/* Determina a customer_preceding e a customer_successor da customer determinada pela component.
 * Mesmo código da função superior, com a diferença que se a component estiver na ultima posição da route,
 * o fim da route é decrementado. (Usado quando é preciso remover a customer de uma route para outra).
 *
 * Variáveis:
 *   - (int)  component, route_end, customer_preceding, customer_successor.
 *   - (int*) route.
 */ 
//這在需要從一個路由移除一個客戶並將其添加到另一個路由時會用到
//C語言宏
//#define get_customer_preceding_and_successor_dec_route_end(component, route, route_end, customer_preceding, customer_successor) \
//    if (component == 0) { \
//        customer_preceding = 0; \
//        customer_successor = route[1]; \
//    } else if (component == route_end -1) { \
//        customer_preceding = route[component -1]; \
//        customer_successor = 0; \
//        route_end--; \
//    } else{ \
//        customer_preceding = route[component -1]; \
//        customer_successor = route[component +1]; \
//    }

//從宏轉成C++函數
void get_customer_preceding_and_successor_dec_route_end(int component, int* route, int& route_end, int& customer_preceding, int& customer_successor) {
    if (component == route_end - 1) {
        if (component == 0) {
            customer_preceding = 0;
        }
        else {
            customer_preceding = route[component - 1];
        }
        customer_successor = 0;
        route_end--;
    }
    else if (component == 0) {
        customer_preceding = 0;
        customer_successor = route[1];
    }
    else {
        customer_preceding = route[component - 1];
        customer_successor = route[component + 1];
    }
}



/* Calcula o cost do indivíduo com a remoção da customer.
 * Não deve ser usado caso a route esteja vazia, pois é adicionado o cost da customer anterior a customer posterior,
 * mas mesmo que neste caso o valor ainda será correto, será menos eficiente.
 *
 * Variáveis:
 *   - (int)   cost, customer_preceding, customer_successor, customer.
 *   - (int**) distances.
 */ 
//#define calculate_customer_remotion(cost, distances, customer_preceding, customer_successor, customer) \
//    cost - distances[customer_preceding][customer] \
//         - distances[customer][customer_successor] \
//         + distances[customer_preceding][customer_successor]
int calculate_customer_remotion(int cost, int** distances, int customer_preceding, int customer_successor, int customer, Individual* individual,int customers_num) {
    if (debug==1) {
        individual_print(individual, individual->vehicles_num_K, customers_num);
    }
    //針對顧客i沒轉移(i為customer)
    if (individual->Customer_Transfer[customer] == 0) {
        //判斷customer_successor
            //判斷顧客i後面顧客J(customer_successor)是否為沒有轉移
        if (individual->Customer_Transfer[customer_successor] == 0) {
            //不做動作
        }
        //否，找出顧客i後面顧客J(customer_successor)後面沒轉移 or 0
        else {
            //目前customer_successor所在路線
            int route = individual->positions[0][customer_successor];
            //目前customer_successor所在路線index
            int index = individual->positions[1][customer_successor];
            //迴圈直到找到後面沒轉移 or 0
                //customer_successor給目前找到顧客，看有沒有找到
            while (individual->Customer_Transfer[customer_successor] != 0 && customer_successor != 0) {
                //後面一位
                index++;
                //避免超過陣列
                if (index < individual->routes_end[route]) {
                    if (debug == 1) {
                        printf("route_end=%d    ", individual->routes_end[route]);
                        printf("index=%d\n", index);
                    }
                    customer_successor = individual->routes[route][index];
                }
                else {
                    customer_successor = 0;
                    continue;
                }
            }
        }
        //判斷customer_preceding
            //判斷顧客i後面顧客J(customer_preceding)是否為沒有轉移
        if (individual->Customer_Transfer[customer_preceding] == 0) {
            //不做動作
        }
        //否，找出顧客i前面顧客(customer_preceding)前面沒轉移 or 0
        else {
            //目前customer_preceding所在路線
            int route = individual->positions[0][customer_preceding];
            //目前customer_preceding所在路線index
            int index = individual->positions[1][customer_preceding];
            //迴圈直到找到前面沒轉移 or 0
                //customer_preceding給目前找到顧客，看有沒有找到
            while (individual->Customer_Transfer[customer_preceding] != 0 && customer_preceding != 0) {
                //前面一位
                index--;
                //避免超過陣列
                if (index >= 0) {
                    customer_preceding = individual->routes[route][index];
                }
                else {
                    customer_preceding = 0;
                    continue;
                }
            }
        }
        //判斷完，進行正常流程
        return cost - distances[customer_preceding][customer]
            - distances[customer][customer_successor]
            + distances[customer_preceding][customer_successor];
    }
    //針對顧客i轉移(i為customer)
    else {
        return cost;
    }
}


/* Calcula o cost do indivíduo com adição da customer.
 * Não deve ser usado caso a route esteja vazia, pois é removido o cost da customer anterior a customer posterior.
 *
 * Variáveis:
 *   - (int)   cost, customer_preceding, customer_successor, customer.
 *   - (int**) distances.
 */
//#define calculate_customer_insertion(cost, distances, customer_preceding, customer_successor, customer) \
//    cost + distances[customer_preceding][customer] \
//         + distances[customer][customer_successor] \
//         - distances[customer_preceding][customer_successor]
int calculate_customer_insertion(int cost, int** distances, int customer_preceding, int customer_successor, int customer, Individual* individual) {
    //針對顧客x沒轉移(x為customer)
    if (individual->Customer_Transfer[customer] == 0) {
        //判斷customer_successor
            //判斷customer_successor是否為沒有轉移
        if (individual->Customer_Transfer[customer_successor] == 0) {
            //不做動作
        }
        //否，找出customer_successor後面沒轉移 or 0
        else {
            //目前customer_successor所在路線
            int route = individual->positions[0][customer_successor];
            //目前customer_successor所在路線index
            int index = individual->positions[1][customer_successor];
            //迴圈直到找到後面沒轉移 or 0
                //customer_successor給目前找到顧客，看有沒有找到
            while (individual->Customer_Transfer[customer_successor] != 0 && customer_successor != 0) {
                //後面一位
                index++;
                //避免超過陣列
                if (index < individual->routes_end[route]) {
                    if (debug == 1) {
                        printf("route_end=%d    ", individual->routes_end[route]);
                        printf("index=%d\n", index);
                    }
                    customer_successor = individual->routes[route][index];
                }
                else {
                    customer_successor = 0;
                    continue;
                }
            }
        }
        //判斷customer_preceding
            //判斷customer_preceding是否為沒有轉移
        if (individual->Customer_Transfer[customer_preceding] == 0) {
            //不做動作
        }
        //否，找出customer_preceding前面沒轉移 or 0
        else {
            //目前customer_preceding所在路線
            int route = individual->positions[0][customer_preceding];
            //目前customer_preceding所在路線index
            int index = individual->positions[1][customer_preceding];
            //迴圈直到找到前面沒轉移 or 0
                //customer_preceding給目前找到顧客，看有沒有找到
            while (individual->Customer_Transfer[customer_preceding] != 0 && customer_preceding != 0) {
                //前面一位
                index--;
                //避免超過陣列
                if (index >= 0) {
                    customer_preceding = individual->routes[route][index];
                }
                else {
                    customer_preceding = 0;
                    continue;
                }
            }
        }
        //判斷完，進行正常流程
        return cost + distances[customer_preceding][customer]
            + distances[customer][customer_successor]
            - distances[customer_preceding][customer_successor];
    }
    //針對顧客x轉移(x為customer)
    else {
        return cost;
    }
}



/* Calcula o cost do indivíduo com a troca da customer_old pela customer_new.
 *
 * Variáveis:
 *   - (int)   cost, customer_preceding, customer_successor, customer_old, customer_new.
 *   - (int**) distances.
 */
//#define calculate_swap_cost_exclusive(cost, distances, customer_preceding, customer_successor, customer_old, customer_new) \
//    cost - distances[customer_preceding][customer_old]  \
//         - distances[customer_old][customer_successor] \
//         + distances[customer_preceding][customer_new]    \
//         + distances[customer_new][customer_successor]
int calculate_swap_cost_exclusive(int cost, int** distances, int customer_preceding, int customer_successor, int customer_old, int customer_new, Individual* individual) {
    if (debug == 1) {
        printf("start calculate_swap_cost_exclusive\n");
        printf("customer_old=%d    customer_new=%d\n", customer_old, customer_new);
        printf("執行前cost=%d\n", cost);
    }
    //getchar();
   //判斷customer_successor
            //判斷customer_successor是否為沒有轉移
    if (debug == 1) {
        printf("Customer_Transfer[customer_successor=%d]=%d\n", customer_successor, individual->Customer_Transfer[customer_successor]);
    }
    if (individual->Customer_Transfer[customer_successor] == 0) {
        //不做動作
        if (debug == 1) {
            printf("calculate_swap_cost_exclusive=>customer_successor=不做動作\n");
        }
    }
    //否，找出customer_successor後面沒轉移 or 0
    else {
        //目前customer_successor所在路線
        int route = individual->positions[0][customer_successor];
        //目前customer_successor所在路線index
        int index = individual->positions[1][customer_successor];
        //迴圈直到找到後面沒轉移 or 0
            //customer_successor給目前找到顧客，看有沒有找到
        while (individual->Customer_Transfer[customer_successor] != 0 && customer_successor != 0 ) {
            //後面一位
            index++;
            //避免超過陣列
            if (index < individual->routes_end[route]) {
                if (debug == 1) {
                    printf("route_end=%d    ", individual->routes_end[route]);
                    printf("index=%d\n", index);
                }
                customer_successor = individual->routes[route][index];
            }
            else {
                customer_successor = 0;
                continue;
            }
        }
        if (debug == 1) {
            printf("calculate_swap_cost_exclusive=>customer_successor=%d\n", customer_successor);
        }
    }
   //判斷customer_preceding
            //判斷customer_preceding是否為沒有轉移
    if (debug == 1) {
        printf("Customer_Transfer[customer_preceding=%d]=%d\n", customer_preceding, individual->Customer_Transfer[customer_preceding]);
    }
    if (individual->Customer_Transfer[customer_preceding] == 0) {
        //不做動作
        if (debug == 1) {
            printf("calculate_swap_cost_exclusive=>customer_preceding=不做動作\n");
        }
    }
    //否，找出customer_preceding前面沒轉移 or 0
    else {
        //目前customer_preceding所在路線
        int route = individual->positions[0][customer_preceding];
        //目前customer_preceding所在路線index
        int index = individual->positions[1][customer_preceding];
        //迴圈直到找到前面沒轉移 or 0
            //customer_preceding給目前找到顧客，看有沒有找到
        while (individual->Customer_Transfer[customer_preceding] != 0 && customer_preceding != 0) {
            //前面一位
            index--;
            //避免超過陣列
            if (index >= 0) {
                customer_preceding = individual->routes[route][index];
            }
            else {
                customer_preceding = 0;
                continue;
            }
        }
        if (debug == 1) {
            printf("calculate_swap_cost_exclusive=>customer_preceding=%d\n", customer_preceding);
        }
    }
    //判斷完，進行正常流程
        //針對顧客i顧客x皆沒轉移(i為old，x為new)
    if (debug == 1) {
        printf("Customer_Transfer[customer_old=%d]=%d,Customer_Transfer[customer_new=%d]=%d\n", customer_old, individual->Customer_Transfer[customer_old], customer_new, individual->Customer_Transfer[customer_new]);
    }
    //getchar();
    if (individual->Customer_Transfer[customer_old] ==0 && individual->Customer_Transfer[customer_new] == 0) {
        //照常運作
        if (debug == 1) {
            printf("calculate_swap_cost_exclusive照常運作\n");
        
        printf("減=%d~%d=%d     %d~%d=%d\n", customer_preceding, customer_old, distances[customer_preceding][customer_old], customer_old, customer_successor, distances[customer_old][customer_successor]);
        }
        //cost減
        cost=cost - distances[customer_preceding][customer_old]
            - distances[customer_old][customer_successor];
      //第二階段
       //判斷customer_successor
            //判斷customer_successor是否為沒有轉移
        if (debug == 1) {
            printf("階段二Customer_Transfer[customer_successor=%d]=%d\n", customer_successor, individual->Customer_Transfer[customer_successor]);
        }
        if (individual->Customer_Transfer[customer_successor] == 0 && customer_successor != customer_new) {
            //不做動作
            if (debug == 1) {
                printf("calculate_swap_cost_exclusive=>階段二customer_successor=不做動作\n");
            }
        }
        else if (individual->Customer_Transfer[customer_successor] == 0 && customer_successor == customer_new) {
            customer_successor = customer_old;
        }
        //否，找出customer_successor後面沒轉移 or 0
        else {
            //目前customer_successor所在路線
            int route = individual->positions[0][customer_successor];
            //目前customer_successor所在路線index
            int index = individual->positions[1][customer_successor];
            //迴圈直到找到後面沒轉移 or 0
                //customer_successor給目前找到顧客，看有沒有找到
            while (individual->Customer_Transfer[customer_successor] != 0 && customer_successor != 0 || customer_successor==customer_new) {
                //後面一位
                index++;
                customer_successor = individual->routes[route][index];
            }
            if (debug == 1) {
                printf("calculate_swap_cost_exclusive=>階段二customer_successor=%d\n", customer_successor);
            }
        }
        //加
        //判斷customer_preceding
            //判斷customer_preceding是否為沒有轉移
        if (debug == 1) {
            printf("階段二Customer_Transfer[customer_preceding=%d]=%d\n", customer_preceding, individual->Customer_Transfer[customer_preceding]);
        }
        if (individual->Customer_Transfer[customer_preceding] == 0 && customer_preceding != customer_new) {
            //不做動作
            if (debug == 1) {
                printf("calculate_swap_cost_exclusive=>階段二customer_preceding=不做動作\n");
            }
        }
        else if (individual->Customer_Transfer[customer_preceding] == 0 && customer_preceding == customer_new) {
            customer_preceding = customer_old;
        }
        //否，找出customer_preceding前面沒轉移 or 0
        else {
            //目前customer_preceding所在路線
            int route = individual->positions[0][customer_preceding];
            //目前customer_preceding所在路線index
            int index = individual->positions[1][customer_preceding];
            //迴圈直到找到前面沒轉移 or 0
                //customer_preceding給目前找到顧客，看有沒有找到
            while (individual->Customer_Transfer[customer_preceding] != 0 && customer_preceding != 0 || customer_preceding==customer_new) {
                //前面一位
                index--;
                //避免超過陣列
                if (index >= 0) {
                    customer_preceding = individual->routes[route][index];
                }
                else {
                    customer_preceding = 0;
                    continue;
                }
            }
            if (debug == 1) {
                printf("calculate_swap_cost_exclusive=>階段二customer_preceding=%d\n", customer_preceding);
            }
        }
        if (debug == 1) {
            printf("加=%d~%d=%d     %d~%d=%d\n", customer_preceding, customer_new, distances[customer_preceding][customer_new], customer_new, customer_successor, distances[customer_new][customer_successor]);
        }
        //加
        cost=cost + distances[customer_preceding][customer_new]
            + distances[customer_new][customer_successor];
        if (debug == 1) {
            printf("執行後cost=%d\n", cost);
        }
        return cost;
    }
    //針對顧客i轉移 顧客x沒轉移(i為old，x為new)
    else if (individual->Customer_Transfer[customer_old] == 1 && individual->Customer_Transfer[customer_new] == 0) {
        //只執行3和4加法
        if (debug == 1) {
            printf("calculate_swap_cost_exclusive只執行3和4加法\n");
        }
        return cost + distances[customer_preceding][customer_new]
            + distances[customer_new][customer_successor];
    }
    //針對顧客i沒轉移 顧客x轉移(i為old，x為new)
    else if (individual->Customer_Transfer[customer_old] == 1 && individual->Customer_Transfer[customer_new] == 0) {
        //只執行1和2加法
        if (debug == 1) {
            printf("calculate_swap_cost_exclusive只執行1和2加法\n");
        }
        return cost - distances[customer_preceding][customer_old]
            - distances[customer_old][customer_successor];
    }
    //針對顧客i顧客x皆轉移(i為old，x為new)
    else {
        //continue 不做事
        if (debug == 1) {
            printf("calculate_swap_cost_exclusive不做事\n");
        }
        return cost;
    }
}



/* Calcula o cost do indivíduo com a troca da customeri pela customerj.
 */
//#define calculate_swap_cost_inclusive(routes, distances, cost_new, cost, i, j, customeri, routei, icustomer_preceding, icustomer_successor, customerj, routej, jcustomer_preceding, jcustomer_successor) \
//    if (i == j-1) { \
//        cost_new = cost - distances[icustomer_preceding][customeri] \
//                        - distances[customerj][jcustomer_successor] \
//                        + distances[customerj][icustomer_preceding] \
//                        + distances[customeri][jcustomer_successor]; \
//    } else { \
//        cost_new = cost + calculate_swap_cost_exclusive(0, distances, icustomer_preceding, icustomer_successor, customeri, customerj) \
//                        + calculate_swap_cost_exclusive(0, distances, jcustomer_preceding, jcustomer_successor, customerj, customeri); \
//    }
int calculate_swap_cost_inclusive(int** routes, int** distances, int cost, int i, int j,
    int customeri, int routei, int icustomer_preceding, int icustomer_successor,
    int customerj, int routej, int jcustomer_preceding, int jcustomer_successor,Individual* individual,int customers_num) {
    int cost_new = 0;
    //判斷ij有無在旁邊
    if (i == j - 1) {
        if (debug == 1) {
            printf("ij在旁邊\n");
        }
        //針對顧客i顧客j皆沒轉移(i為customeri，j為customerj)
        if (individual->Customer_Transfer[customeri] ==0 && individual->Customer_Transfer[customerj] == 0) {
            //判斷jcustomer_successor
                //判斷jcustomer_successor是否為沒有轉移
            if (debug == 1) {
                printf("Customer_Transfer[customer_successor=%d]=%d\n", jcustomer_successor, individual->Customer_Transfer[jcustomer_successor]);
            }
            if (individual->Customer_Transfer[jcustomer_successor] == 0) {
                //不做動作
                if (debug == 1) {
                    printf("calculate_swap_cost_exclusive=>jcustomer_successor=不做動作\n");
                }
            }
            //否，找出customer_successor後面沒轉移 or 0
            else {
                //目前customer_successor所在路線
                int route = individual->positions[0][jcustomer_successor];
                //目前customer_successor所在路線index
                int index = individual->positions[1][jcustomer_successor];
                //迴圈直到找到後面沒轉移 or 0
                    //customer_successor給目前找到顧客，看有沒有找到
                while (individual->Customer_Transfer[jcustomer_successor] != 0 && jcustomer_successor != 0) {
                    //後面一位
                    index++;
                    //避免超過陣列
                    if (index < individual->routes_end[route]) {
                        if (debug == 1) {
                            printf("route_end=%d    ", individual->routes_end[route]);
                            printf("index=%d\n", index);
                        }
                        jcustomer_successor = individual->routes[route][index];
                    }
                    else {
                        jcustomer_successor = 0;
                        continue;
                    }
                }
                if (debug == 1) {
                    printf("calculate_swap_cost_exclusive=>jcustomer_successor=%d\n", jcustomer_successor);
                }
            }
            //判斷icustomer_preceding
                        //判斷customer_preceding是否為沒有轉移
            if (debug == 1) {
                printf("Customer_Transfer[icustomer_preceding=%d]=%d\n", icustomer_preceding, individual->Customer_Transfer[icustomer_preceding]);
            }
            if (individual->Customer_Transfer[icustomer_preceding] == 0) {
                //不做動作
                if (debug == 1) {
                    printf("calculate_swap_cost_exclusive=>customer_preceding=不做動作\n");
                }
            }
            //否，找出customer_preceding前面沒轉移 or 0
            else {
                //目前customer_preceding所在路線
                int route = individual->positions[0][icustomer_preceding];
                //目前customer_preceding所在路線index
                int index = individual->positions[1][icustomer_preceding];
                //迴圈直到找到前面沒轉移 or 0
                    //customer_preceding給目前找到顧客，看有沒有找到
                while (individual->Customer_Transfer[icustomer_preceding] != 0 && icustomer_preceding != 0) {
                    //前面一位
                    index--;
                    //避免超過陣列
                    if (index >= 0) {
                        icustomer_preceding = individual->routes[route][index];
                    }
                    else {
                        icustomer_preceding = 0;
                        continue;
                    }
                }
                if (debug == 1) {
                    printf("calculate_swap_cost_exclusive=>icustomer_preceding=%d\n", icustomer_preceding);
                }
            }
            //判斷完，進行正常流程
                    //照常運作
            return cost_new = cost - distances[icustomer_preceding][customeri]
                - distances[customerj][jcustomer_successor]
                + distances[customerj][icustomer_preceding]
                + distances[customeri][jcustomer_successor];
        }
        //其他情況皆不須執行與變動
        else {
            //continue 不做事
            return cost;
        }
    }
    //如果沒有相鄰，執行兩次calculate_swap_cost_exclusive()
    else {
        if (debug == 1) {
            printf("ij不在旁邊要執行兩次calculate_swap_cost_exclusive()\n");
            printf("customeri=%d    customerj=%d\n", customeri, customerj);
            individual_print(individual, individual->vehicles_num_K, customers_num);
            printf("執行第一次\n");
        }
        cost_new = cost + calculate_swap_cost_exclusive(0, distances, icustomer_preceding, icustomer_successor, customeri, customerj, individual);
        if (debug == 1) {
            printf("執行完後第一次customeri=%d    customerj=%d     icustomer_preceding=%d     icustomer_successor=%d\n", customeri, customerj, icustomer_preceding, icustomer_successor);
            printf("\n執行第二次\n");
        }
        cost_new =cost_new + calculate_swap_cost_exclusive(0, distances, jcustomer_preceding, jcustomer_successor, customerj, customeri,individual);
        if (debug == 1) {
            printf("執行完後第二次customerj=%d    customeri=%d     jcustomer_preceding=%d     jcustomer_successor=%d\n", customerj, customeri, jcustomer_preceding, jcustomer_successor);
            printf("cost_new更新為%d\n",cost_new);
        }
        
    }
    return cost_new;
}

/*customer_transfer 0->1時計算成本*/
int calculate_customer_transfer_remotion(int cost, int** distances, int customer_preceding, int customer_successor, int customer, Individual* individual,int customers_num) {
    if (debug == 1) {
        individual_print(individual, individual->vehicles_num_K, customers_num);
    }
   //判斷customer_successor
        //判斷顧客i後面顧客J(customer_successor)是否為沒有轉移
    if (individual->Customer_Transfer[customer_successor] == 0) {
        //不做動作
    }
    //否，找出顧客i後面顧客J(customer_successor)後面沒轉移 or 0
    else {
        //目前customer_successor所在路線
        int route = individual->positions[0][customer_successor];
        //目前customer_successor所在路線index
        int index = individual->positions[1][customer_successor];
        //迴圈直到找到後面沒轉移 or 0
            //customer_successor給目前找到顧客，看有沒有找到
        while (individual->Customer_Transfer[customer_successor] != 0 && customer_successor != 0) {
            //後面一位
            index++;
            //避免超過陣列
            if (index < individual->routes_end[route]) {
                if (debug == 1) {
                    printf("route_end=%d    ", individual->routes_end[route]);
                    printf("index=%d\n", index);
                }
                customer_successor = individual->routes[route][index];
            }
            else {
                customer_successor = 0;
                continue;
            }
        }
    }
   //判斷customer_preceding
        //判斷顧客i後面顧客J(customer_preceding)是否為沒有轉移
    if (individual->Customer_Transfer[customer_preceding] == 0) {
        //不做動作
    }
    //否，找出顧客i前面顧客(customer_preceding)前面沒轉移 or 0
    else {
        //目前customer_preceding所在路線
        int route = individual->positions[0][customer_preceding];
        //目前customer_preceding所在路線index
        int index = individual->positions[1][customer_preceding];
        //迴圈直到找到前面沒轉移 or 0
            //customer_preceding給目前找到顧客，看有沒有找到
        while (individual->Customer_Transfer[customer_preceding] != 0 && customer_preceding != 0) {
            //前面一位
            index--;
            //避免超過陣列
            if (index >= 0) {
                customer_preceding = individual->routes[route][index];
            }
            else {
                customer_preceding = 0;
                continue;
            }
        }
    }
    //判斷完，進行正常流程
    return cost - distances[customer_preceding][customer]
        - distances[customer][customer_successor]
        + distances[customer_preceding][customer_successor];
}
/*customer_transfer 1->0時計算成本*/
int calculate_customer_transfer_insertion(int cost, int** distances, int customer_preceding, int customer_successor, int customer, Individual* individual) {
    
   //判斷customer_successor
        //判斷customer_successor是否為沒有轉移
    if (individual->Customer_Transfer[customer_successor] == 0) {
        //不做動作
    }
    //否，找出customer_successor後面沒轉移 or 0
    else {
        //目前customer_successor所在路線
        int route = individual->positions[0][customer_successor];
        //目前customer_successor所在路線index
        int index = individual->positions[1][customer_successor];
        //迴圈直到找到後面沒轉移 or 0
            //customer_successor給目前找到顧客，看有沒有找到
        while (individual->Customer_Transfer[customer_successor] != 0 && customer_successor != 0) {
            //後面一位
            index++;
            //避免超過陣列
            if (index < individual->routes_end[route]) {
                if (debug == 1) {
                    printf("route_end=%d    ", individual->routes_end[route]);
                    printf("index=%d\n", index);
                }
                customer_successor = individual->routes[route][index];
            }
            else {
                customer_successor = 0;
                continue;
            }
        }
    }
   //判斷customer_preceding
        //判斷customer_preceding是否為沒有轉移
    if (individual->Customer_Transfer[customer_preceding] == 0) {
        //不做動作
    }
    //否，找出customer_preceding前面沒轉移 or 0
    else {
        //目前customer_preceding所在路線
        int route = individual->positions[0][customer_preceding];
        //目前customer_preceding所在路線index
        int index = individual->positions[1][customer_preceding];
        //迴圈直到找到前面沒轉移 or 0
            //customer_preceding給目前找到顧客，看有沒有找到
        while (individual->Customer_Transfer[customer_preceding] != 0 && customer_preceding != 0) {
            //前面一位
            index--;
            //避免超過陣列
            if (index >= 0) {
                customer_preceding = individual->routes[route][index];
            }
            else {
                customer_preceding = 0;
                continue;
            }
        }
    }
   //判斷完，進行正常流程
    return cost + distances[customer_preceding][customer]
        + distances[customer][customer_successor]
        - distances[customer_preceding][customer_successor];
}

/*轉移機制*/
/*從不轉移變轉移 individual->Customer_Transfer[]=0->1*/
void calculate_customer_turnto_transfer(int** distances, Individual* individual, int customers_num, Customer* customers,Individual* Fixed_Route_individual, int transfer_cost_once, int capacity_max) {
    //random 一個customer
    int customer = (rand() % (customers_num-1))+1;
    
    if (individual->Customer_Transfer[customer]==1) {
        //找此顧客前後
        //printf("customer=%d\n",customer);
        //已經是轉移直接離開即可
        return;
    }
    else {
         int customer_preceding = 0,
            customer_successor = 0,
            index_rota = individual->positions[0][customer],
            route_end = individual->routes_end[index_rota];

        int* route = individual->routes[index_rota];
        int component = individual->positions[1][customer];
        //判斷顧客在該固定路線轉移空間是否足夠
        if (customers[customer].demand <= individual->Transfer_Car_Capacities_Free[Fixed_Route_individual->positions[0][customer]]) {
            //判斷轉移是否較節省
                //找此顧客前後
            get_customer_preceding_and_successor_dec_route_end(component, route, route_end, customer_preceding, customer_successor);
                //計算轉移後成本
            int change_cost = calculate_customer_remotion(individual->cost, distances, customer_preceding, customer_successor, customer, individual, customers_num);
            //判斷individual->Transfer_Car_Totol_Capacities_Free總轉移車輛剩餘空間
                //總轉移車輛剩餘空間>=改變後cost
            if (individual->Transfer_Car_Totol_Capacities_Free >= change_cost) {
                //判斷改變後cost小於individual->cost
                if (change_cost<individual->cost) {
                    //辦理轉移
                    individual->Customer_Transfer[customer] = 1;
                    //覆蓋成好的解
                    individual->cost = change_cost;
                    //扣掉總轉移車輛空間
                    individual->Transfer_Car_Totol_Capacities_Free -= customers[customer].demand;
                    //扣掉固定路線轉移空間
                    individual->Transfer_Car_Capacities_Free[Fixed_Route_individual->positions[0][customer]] -= customers[customer].demand;
                }
            }
            //小於要加上transfer_cost_once
            else {
                //判斷改變後cost小於individual->cost
                if (change_cost<individual->cost) {
                    //辦理轉移
                    individual->Customer_Transfer[customer] = 1;
                    //覆蓋成好的解 + transfer_cost_once
                    individual->cost =( change_cost + transfer_cost_once);
                    //Transfer_Car_Number + 1 
                    individual->Transfer_Car_Number += 1;
                    //扣掉總轉移車輛空間+新車輛空間
                    individual->Transfer_Car_Totol_Capacities_Free -= customers[customer].demand;
                    individual->Transfer_Car_Totol_Capacities_Free += capacity_max;
                    //扣掉固定路線轉移空間
                    individual->Transfer_Car_Capacities_Free[Fixed_Route_individual->positions[0][customer]] -= customers[customer].demand;
                }
            }
        }
        //不夠直接提開
        else {
            return;
        }
    }
}
/*從轉移變不轉移 individual->Customer_Transfer[]=1->0*/
void calculate_customer_turnto_notransfer(int** distances, Individual* individual, int customers_num, Customer* customers, Individual* Fixed_Route_individual, int transfer_cost_once, int capacity_max) {
    //將有轉移顧客放進暫時陣列中
    int* transfer_customers=(int*)malloc(sizeof(int)*customers_num);
    int count = 0;
    for (int i = 1; i < customers_num;i++) {
        if (individual->Customer_Transfer[i] == 1) {
            count++;
            transfer_customers[count] = i;            
        }
    }
    //random一個有轉移顧客->unless都沒有
    if (count==0){
        return;
    }
    else {
        //random 一個有轉移customer
        int random = (rand() % (count)+1);
        int customer = transfer_customers[random];
        //辦理不轉移
        individual->Customer_Transfer[customer] = 0;
        int customer_preceding = 0,
            customer_successor = 0,
            index_rota = individual->positions[0][customer],
            route_end = individual->routes_end[index_rota];

        int* route = individual->routes[index_rota];
        int component = individual->positions[1][customer];
        //找此顧客前後
        get_customer_preceding_and_successor_dec_route_end(component, route, route_end, customer_preceding, customer_successor);
        //計算不轉移後成本
        int change_cost = calculate_customer_insertion(individual->cost, distances, customer_preceding, customer_successor, customer, individual);
        //加上總轉移車輛空間
        individual->Transfer_Car_Totol_Capacities_Free += customers[customer].demand;
        //判斷individual->Transfer_Car_Totol_Capacities_Free是否 大於等於 capacity_max
        if (individual->Transfer_Car_Totol_Capacities_Free >=capacity_max) {
            //減少一輛車
            individual->Transfer_Car_Number--;
            //扣除一輛轉移車輛費用
            change_cost -= transfer_cost_once;
        }
        //覆蓋成好的解
        individual->cost = change_cost;
    }
    free(transfer_customers);
}
/*轉移機制*/


void local_search(Individual* trial, int** distances, Customer* customers, int vehicles_num,Individual* Fixed_Route_individual,int transfer_cost_once, int capacity_max,int customers_num) {
    int it_no_improvement_cnt = 0;
    int original_cost = trial->cost;
    
    do {
        if (debug == 1) {
            printf("LS original_cost=%d    ", original_cost);
        }

        /*新增轉移不轉移機制*/
      //printf("轉移前cost=%d\n",trial->cost);
        calculate_customer_turnto_transfer(distances, trial, customers_num, customers, Fixed_Route_individual, transfer_cost_once, capacity_max);
        //printf("轉移後cost=%d\n", trial->cost);
        //getchar();
        /*新增轉移不轉移機制*/

        two_swap(trial, distances, customers, trial->vehicles_num_K, customers_num);
        if (debug == 1) {
            printf("two_swap後trial->cost=%d\n", trial->cost);
            individual_print(trial, trial->vehicles_num_K, customers_num);
        }

        

        if (original_cost > trial->cost) {
            original_cost = trial->cost;
            it_no_improvement_cnt = 0;
            if (debug == 1) {
                printf("original_cost=%d    trial->cost=%d      ", original_cost,trial->cost);
                printf("LS第一階段有改進\n");
            }
        } else {
            it_no_improvement_cnt++;
            if (debug == 1) {
            printf("LS第一階段沒有改進\n");
            }
        }
        
        
        if (it_no_improvement_cnt > 1) {
            break;
        }
        
        strong_drop_one_point(trial, distances, customers, vehicles_num, customers_num);
        if (original_cost > trial->cost) {
            if (debug == 1) {
                printf("strong_drop_one_point       original_cost=%d    trial->cost=%d      ", original_cost, trial->cost);
                printf("LS第二階段有改進\n");
                individual_print(trial, trial->vehicles_num_K, customers_num);
            }
            original_cost = trial->cost;
            it_no_improvement_cnt = 0;
            
        } else {
            it_no_improvement_cnt++;
            if (debug == 1) {
                printf("LS第二階段沒有改進\n");
                individual_print(trial, trial->vehicles_num_K, customers_num);
            }
        }
       
        if (!trial->feasible) {
            drop_one_point_infeasible(trial, distances, customers, vehicles_num, customers_num);
            if (debug == 1) {
                individual_print(trial, trial->vehicles_num_K, customers_num);
            }
            if (trial->feasible) {
                it_no_improvement_cnt = 0;
            }
            else {
                calculate_customer_turnto_notransfer(distances, trial, customers_num, customers, Fixed_Route_individual, transfer_cost_once, capacity_max);
                individual_reevaluate(trial, capacity_max, vehicles_num, distances, customers, Fixed_Route_individual, transfer_cost_once);
            }
        }
        if (debug == 1) {
            printf("LS一次後cost=%d\n", trial->cost);
            individual_print(trial, trial->vehicles_num_K, customers_num);
            getchar();
        }
    } while (it_no_improvement_cnt < 2);
    if (debug == 1) {
        printf("LS偵錯點2\n");
    }
    return;
}


void two_swap(Individual* individual, int** distances, Customer* customers, int vehicles_num,int customers_num) {
    int i = 0, //routei index
        j = 0,//routej index
        routei = 0,
        routej = 0,
        load = 0, 
        loadj = 0,
        customeri = 0, 
        customerj = 0,
        route_endi = 0, 
        route_endj = 0,
        icustomer_preceding = 0, 
        icustomer_successor = 0,
        jcustomer_preceding = 0, 
        jcustomer_successor = 0;
     
    int *route = NULL;
    
    int cost_new = 0,
        original_cost = individual->cost;
    if (debug == 1) {
        printf("into two_swap   ");
        printf("two_swap original_cost=%d\n", original_cost);
        individual_print(individual, individual->vehicles_num_K, customers_num);
    }
    int it_got_improvement = 0;
        
    for (routei = 0; routei < vehicles_num; routei++) {
    
        route_endi = individual->routes_end[routei];
        for (i = 0; i < route_endi; i++) {
RESTART_MOVEMENT_2SWAP://重跑一次該路線從index0開始(確定有更好才會執行)
            customeri = individual->routes[routei][i];
            if (individual->Customer_Transfer[customeri] == 0) {
                load = customers[customeri].demand;
            }
            else {
                load = 0;
            }
            if (debug == 1) {
                printf("routei=%d   i=%d    customeri=%d    ", routei, i, customeri);
            }
            for (routej = routei; routej < vehicles_num; routej++) {
                if (debug == 1) {
                    printf("routej=%d   ", routej);
                }
                route_endj = individual->routes_end[routej];
                //j從路線中第幾個index開始
                if (routei == routej) {
                    j = i+1;
                } else {
                    j = 0;
                }
                if (debug == 1) {
                    printf("j star from %d  ", j);
                }
                for (; j < route_endj; j++) {
                    if (debug == 1) {
                        printf("j now is %d  route_endj=%d  ", j, route_endj);
                    }
                    /*在考慮交換兩個點的位置時，如果它們已經在同一條路徑上，那麼這樣的交換動作不會使該解變得不可行*/
                    
                    customerj = individual->routes[routej][j];
                    if (individual->Customer_Transfer[customeri] == 0) {
                        loadj = customers[customerj].demand;
                    }
                    else {
                        loadj = 0;
                    }
                    if (debug == 1) {
                        printf("customerj=%d\n", customerj);
                    }
                    //不同路線
                    if (routei != routej) {
                        if (debug == 1) {
                            printf("不同路線swap\n");
                        }
                        //將自己需求移出所在路線，如果該路線剩餘空間放不下要將換對象需求，不做
                        if ((individual->capacities_free[routei] + load < loadj) || (individual->capacities_free[routej] + loadj < load)) {
                            if (debug == 1) {
                                printf("沒有剩餘空間swap\n");
                            }
                            continue;
                        } else {
                            if (debug == 1) {
                                printf("有剩餘空間swap\n");
                            }
                            route = individual->routes[routei];
                            //
                            route[route_endi] = 0;
                            get_customer_preceding_and_successor(i, route, route_endi, icustomer_preceding, icustomer_successor,individual); /* Macro */
                        
                            route = individual->routes[routej];
                            route[route_endj] = 0;
                            get_customer_preceding_and_successor(j, route, route_endj, jcustomer_preceding, jcustomer_successor,individual);
                            
                            if (debug == 1) {
                                printf("======================start===========================\n");
                                individual_print(individual, individual->vehicles_num_K, customers_num);
                                printf("two_swap cost_new改動前=%d    ", cost_new);
                                printf("要swap的 i為 %d ,j為 %d\n", individual->routes[routei][i], individual->routes[routej][j]);
                                printf("icustomer_preceding=%d , customeri=%d , icustomer_successor=%d , customerj=%d\n", icustomer_preceding, customeri, icustomer_successor, customerj);
                                printf("jcustomer_preceding=%d , customerj=%d , jcustomer_successor=%d , customeri=%d\n", jcustomer_preceding, customerj, jcustomer_successor, customeri);
                            }
                            cost_new = original_cost + calculate_swap_cost_exclusive(0, distances, icustomer_preceding, icustomer_successor, customeri, customerj,individual)
                                            + calculate_swap_cost_exclusive(0, distances, jcustomer_preceding, jcustomer_successor, customerj, customeri,individual);
                            if (debug == 1) {
                                printf("two_swap cost_new改動後=%d\n", cost_new);
                            }
                            
                            if (cost_new < original_cost) {
                                original_cost = cost_new;
                                individual_swap_customers(individual, customeri, load, customerj, loadj);
                                if (debug == 1) {
                                    individual_print(individual, individual->vehicles_num_K, customers_num);
                                    printf("=========================end==========================\n");
                                }
                                it_got_improvement = 1; 
                            }
                            if (debug == 1) {
                                printf("一次個體two swap\n");
                            }
                            //getchar();
                        }
                    } 
                    //同路線swap
                    else {
                        if (debug == 1) {
                            printf("同路線swap ");
                        }
                        route = individual->routes[routei];
                        get_customer_preceding_and_successor(i, route, route_endi, icustomer_preceding, icustomer_successor,individual); /* Macro */
                    
                        route = individual->routes[routej];
                        get_customer_preceding_and_successor(j, route, route_endj, jcustomer_preceding, jcustomer_successor,individual); /* Macro */
                        if (debug == 1) {
                            printf("into calculate_swap_cost_inclusive\n");
                        }
                        //individual_print(individual, individual->vehicles_num_K);
                        cost_new= calculate_swap_cost_inclusive(individual->routes, distances, original_cost, i, j, customeri, routei, icustomer_preceding, icustomer_successor, customerj, routej, jcustomer_preceding, jcustomer_successor,individual, customers_num);
                        if (debug == 1) {
                            printf("============================================\n");
                            printf("cost_new=%d original_cost=%d\n", cost_new, original_cost);
                            printf("============================================\n");
                        }

                        if (cost_new < original_cost) {
                            original_cost = cost_new;
                            individual_swap_customers(individual, customeri, 0, customerj, 0); /* Como estão na mesma route, as cargas não mudarão */
                            if (debug == 1) {
                                printf("cost_new < original_cost    ");
                                printf("original_cost更新後為%d\n", original_cost);
                                individual_print(individual, individual->vehicles_num_K, customers_num);
                                printf("<============================================>\n");
                            }
                            it_got_improvement = 1;
                        }
                        //getchar();
                    }
                    
                    if (it_got_improvement) {
                        it_got_improvement = 0;
                        if (debug == 1) {
                            printf("goto RESTART_MOVEMENT_2SWAP\n");
                        }
                        goto RESTART_MOVEMENT_2SWAP;
                    }
                }
            }
        }
    }
    if (debug == 1) {
        printf("結束一次世代two_swap\n");
        //getchar();
    }
    if (!individual->feasible) {
        i = 0;
        while (i < vehicles_num && individual->capacities_free[i] >=0) {
            i++;
        }

        if (i == vehicles_num) {
            individual->cost = original_cost - PENALTY;
            individual->feasible = 1;
            return;
        }
    }
    
    individual->cost = original_cost;
    return;
}


int drop_one_point_infeasible(Individual* individual, int** distances, Customer* customers, int vehicles_num,int customers_num) {
    int infeasible = 1;

    /* Obtaining route with highest load */
    int i = 0,
        route_highest_load = 0,
        highest_free_capacity = 0;

    for (i = 0; i < vehicles_num; i++) {
        if (individual->capacities_free[i] > highest_free_capacity) {
            highest_free_capacity = individual->capacities_free[i];
            route_highest_load = i;
        }
    }

    int *route = NULL;
    
    int load = 0,
        customer = 0,
        route_end = 0,
        retry_cnt = 0,
        retry_max = 0,
        route_chosen = 0,
        route_invalid = 0;
    do {    
        /* Selecionando uma route inválida aleatória */
        do {
            route_invalid = rand() % vehicles_num;
        } while (individual->capacities_free[route_invalid] >= 0); //TODO: make a list of infeasible routes
        
        route = individual->routes[route_invalid];
        route_end = individual->routes_end[route_invalid];
        
        /* Tentativa de selecionar uma customer aleatória na route que estourou a capacidade */
        retry_cnt = 0;
        retry_max = route_end + route_end/2;
        do {
            if (retry_cnt == retry_max) {
                return -1; /* Algoritmo chegou ao máximo de retry_cnt e não encontrou uma customer que pudesse ser realocada naquela route */
            }
        
            customer = route[rand() % route_end];
            if (individual->Customer_Transfer[customer] == 0) {
                load = customers[customer].demand;
            }
            else {
                load = 0;
            }
            
            retry_cnt++;
        } while (highest_free_capacity < load);
        
        
        /* Selecionando uma route aleatória para realocar a customer selecionada */
        do {
            route_chosen = rand() % vehicles_num;
        } while (individual->capacities_free[route_chosen] < load);

        reinsert_customer_best_position_in_another_route(individual, distances, customer, load, route_chosen, customers_num);

//      individual->capacities_free[num_rota] -= load;
//      individual->capacities_free[route_invalid] += load;

        //Se a route selecionada foi a route de maior load disponivel, a maior load disponivel será recalculada.
        if (route_chosen == route_highest_load) {
            highest_free_capacity -= load;
            for (i = 0; i < vehicles_num; i++) {
                if (highest_free_capacity < individual->capacities_free[i]) {
                    highest_free_capacity = individual->capacities_free[i];
                    route_highest_load = i;
                }
            }
        }
        
        /* Será verificado se o individual viabilizou */
        if (individual->capacities_free[route_invalid] >= 0) {
            for (i = 0; i < vehicles_num; i++) {
                if (individual->capacities_free[i] < 0) {
                    break;
                }
            }
            
            if (i == vehicles_num) infeasible = 0;
        }
        
    } while (infeasible);

    individual->feasible = 1;

    return individual->cost = individual->cost - PENALTY;
}


//TODO: can merge it with the other function?
int reinsert_customer_best_position_in_another_route_if_improves(Individual* individual, int** distances, int customer, int load, int new_route_idx,int customers_num) {
    int customer_preceding = 0,
        customer_successor = 0,
        index_rota = individual->positions[0][customer],
        route_end = individual->routes_end[index_rota];

    int* route = individual->routes[index_rota];  
    int component = individual->positions[1][customer];

    get_customer_preceding_and_successor_dec_route_end(component, route, route_end, customer_preceding, customer_successor); /* Macro */
//  printf("%d %d %d %d\n", individual->cost, customer_preceding, customer_successor, customer);
    int custo_base = calculate_customer_remotion(individual->cost, distances, customer_preceding, customer_successor, customer,individual, customers_num); /* Macro */

    //  individual_remove_customer(individual, customer);

    int cost_new = 0;
    if (individual->routes_end[new_route_idx] == 0) {
        cost_new = custo_base + distances[0][customer]
                              + distances[customer][0];

        if (cost_new < individual->cost) {
            individual_remove_customer(individual, customer, load);
            individual_insert_customer(individual, customer, load, 0, new_route_idx);
            individual->cost = cost_new;
            return 1;
        }
        return 0;
    }

    route = individual->routes[new_route_idx]; 
    customer_preceding = 0;
    customer_successor = route[0];
    route_end = individual->routes_end[new_route_idx];

    int index = 0,
        original_cost = INT_MAX,
        nova_posicao = 0;

    route[route_end] = 0;
    route_end++;
    while (index < route_end) {
        cost_new = calculate_customer_insertion(custo_base, distances, customer_preceding, customer_successor, customer,individual); /* Macro */

        if (cost_new < original_cost) {
            original_cost = cost_new;
            nova_posicao = index;
        }

        index++;
        customer_preceding = customer_successor;
        customer_successor = route[index];
    }

    if (original_cost < individual->cost) {
        individual_remove_customer(individual, customer, load);
        individual_insert_customer(individual, customer, load, nova_posicao, new_route_idx);
        individual->cost = original_cost;
        return 1;
    }

    return 0;
}

void reinsert_customer_best_position_in_another_route(Individual* individual, int** distances, int customer, int load, int new_route_idx,int customers_num) {
    int customer_preceding = 0,
        customer_successor = 0,
        index_rota = individual->positions[0][customer],
        route_end = individual->routes_end[index_rota];

    int* route = individual->routes[index_rota];
    int component = individual->positions[1][customer];

    get_customer_preceding_and_successor_dec_route_end(component, route, route_end, customer_preceding, customer_successor); /* Macro */
    int custo_base = calculate_customer_remotion(individual->cost, distances, customer_preceding, customer_successor, customer,individual, customers_num); /* Macro */

    individual_remove_customer(individual, customer, load);

    if (individual->routes_end[new_route_idx] == 0) {
        individual_insert_customer(individual, customer, load, 0, new_route_idx);
        individual->cost = custo_base + distances[0][customer]
                                      + distances[customer][0];
        return;
    }

    route = individual->routes[new_route_idx]; 
    customer_preceding = 0;
    customer_successor = route[0];

    int cost_new,
        nova_posicao = 0,
        original_cost = INT_MAX;

    route_end = individual->routes_end[new_route_idx];
    route[route_end] = 0;
    route_end++;

    int index = 0;
    while (index < route_end) {
        cost_new = calculate_customer_insertion(custo_base, distances, customer_preceding, customer_successor, customer,individual); /* Macro */

        if (cost_new < original_cost) {
            original_cost = cost_new;
            nova_posicao = index;
        }

        index++;
        customer_preceding = customer_successor;
        customer_successor = route[index];
    }

    individual_insert_customer(individual, customer, load, nova_posicao, new_route_idx);
    individual->cost = original_cost;

    return;
}


void strong_drop_one_point(Individual* individual, int** distances, Customer* customers, int vehicles_num,int customers_num) {
    int* rotas_possiveis=new int[vehicles_num];

    int i = 0, 
        load = 0,
        customer = 0,
        route_end = 0,
        route_chosen = 0;

    int load_old = 0,    //TODO: use load, new load instead?
        got_improvement = 0;
    
    int* route = NULL;
    
    int index = 0;
    for (int num_rota = 0; num_rota < vehicles_num; num_rota++) {
    
        route = individual->routes[num_rota];
        route_end = individual->routes_end[num_rota];
        load_old = -1;
        
        /*Se a route só possui uma customer, esta customer será mantida */
        if (route_end > 0) { 
            for (i = 0; i < route_end; i++) {
                customer = route[i];
                if (individual->Customer_Transfer[customer] == 0) {
                    load = customers[customer].demand;
                }
                else {
                    load = 0;
                }
                
                /* Se a load atual é maior que a load anterior ou houve melhora, é necessário recalcular as routes possiveis */
                if (load > load_old || got_improvement) {
                    //Seleciona as routes possiveis, diferentes da route atual, para efetuar o movimento.
                    index = 0;
                    for (int k = 0; k < vehicles_num; k++) {
                        if (k != num_rota && load <= individual->capacities_free[k]) {
                            rotas_possiveis[index] = k;
                            index++;
                        }
                    }
                }
                
                got_improvement = 0;
                for (int l = 0; l < index; l++) {
                    route_chosen = rotas_possiveis[l];
                    if (!got_improvement) {
                        got_improvement = reinsert_customer_best_position_in_another_route_if_improves(individual, distances, customer, load, route_chosen, customers_num);
                    } else {
                        reinsert_customer_best_position_in_another_route_if_improves(individual, distances, customer, load, route_chosen, customers_num);
                    }
                }
                    
                /* Com a melhora, o tamanho das routes modificaram */
                if (got_improvement)
                    route_end = individual->routes_end[num_rota];
                
                load_old = load;
            }
        }
    }

    if (!individual->feasible) {
        i = 0;
        while (i < vehicles_num && individual->capacities_free[i] >=0) i++;

        if (i == vehicles_num) {
            individual->cost -= PENALTY;
            individual->feasible = 1;
        }
    }
    delete rotas_possiveis;
    return;
}
