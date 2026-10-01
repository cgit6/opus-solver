#include <stdlib.h>
#include <string.h>
#include <math.h>

#include "../metaheuristic/differential_evolution.h"


Customer* customer_create(int id, double x, double y) {
    Customer* customer = (Customer*) malloc(sizeof(Customer));
    customer->id = id;
    customer->x = x;
    customer->y = y;
    customer->demand = 0;
    
    return customer;
}


Customer* customer_free(Customer* customer) {
    free(customer);

    return NULL;
}


/* Alternative for ( distance matrix */
/*
int calculate_distance(Customer* c1, Customer* c2) {
    return sqrt( pow( (c1->x - c2->x), 2) + pow( (c1->y - c2->y), 2) ) + 0.5;
}
*/


int** distances_matrix_init(Customer* customers, int customers_num) {
    //距離矩陣
    int** mat = (int**) malloc (customers_num * sizeof(int*));
    for (int i = 0; i < customers_num; i++) {
        mat[i] = (int*) malloc (customers_num * sizeof(int));
    }
    
    int cost = 0;
    Customer *c1 = NULL,
             *c2 = NULL;
    for (int i = 1; i < customers_num; i++) {
        c1 = &customers[i];
        //printf("customers_id=%d , x=%f , y=%f\n", c1->id, c1->x, c1->y);
        for (int j = i -1; j >= 0; j--) {
            c2 = &customers[j];
            //printf("customers_id=%d , x=%f , y=%f\n", c2->id, c2->x, c2->y);
            //計算歐式距離 (+0.5 是為了進行四捨五入。當你後面對這個結果進行整數型態轉換時，它會自動將小數部分捨去，所以加上 0.5 可以確保正確的四捨五入)
            cost = sqrt( pow((c1->x - c2->x), 2) + pow((c1->y - c2->y), 2) ) + 0.5;
            //printf("cost=%d\n",cost);
            mat[i][j] = mat[j][i] = cost;
            //printf("mat[%d][%d]=%d\n",i,j, mat[i][j]);
        }
    }
    
    for (int i = 0; i < customers_num; i++) {
        mat[i][i] = 0;
    }
        
    return mat;
}


int** distances_matrix_free(int** distances, int customers_num) {
    for (int i = 0; i < customers_num; i++) {
        free(distances[i]);
    }
    
    free(distances);

    return NULL;
}

double calculate_transfer_cost(int** distances, int customers_num) {
    double temp = 0.0;
    for (int i = 1; i < customers_num; i++) {
        for (int j = i - 1; j >= 0;j--) {
            if (distances[i][j] > temp) {
                temp = distances[i][j];
                //printf("temp=%lf\n",temp);
            }
        }
    }
    //轉移成本要最遠距離除二
    temp=(temp / 2)+0.5;//四捨五入至整數
    
    return temp;
}
        
Individual* individual_init(int customers_num, int vehicles_num, Individual* Fixed_Route_individual) {//定義與初始化individual
    
    Individual* individual = (Individual*) malloc(sizeof(Individual));
    individual->routes = (int**) malloc(vehicles_num * sizeof(int*));
    
    for (int i = 0; i < vehicles_num; i++) {
        individual->routes[i] = (int*) malloc(customers_num * sizeof(int));
    }

    individual->positions =   (int**) malloc(2 * sizeof(int*));
    individual->positions[0] = (int*) malloc(customers_num * sizeof(int));
    individual->positions[1] = (int*) malloc(customers_num * sizeof(int));
    /*每個顧客 i 的位置都是由 positions[i][...] 來表示的。
    positions[0][i] 表示第 i 個顧客所在的路線編號。
    positions[1][i] 表示第 i 個顧客在其所屬路線中的索引或位置。
    舉例來說，如果 positions[0][5] 的值是 3，並且 positions[1][5] 的值是 7，這表示第5個顧客在第3條路線中，並且他是這條路線的第7個顧客。*/

    //設定場站position
    individual->positions[0][0] = individual->positions[1][0] = 0;

    individual->routes_end = (int*) malloc (vehicles_num * sizeof(int));
    individual->capacities_free = (int*) malloc (vehicles_num * sizeof(int));

    individual->Customer_Transfer = (int*)malloc(customers_num * sizeof(int));
    memset(individual->Customer_Transfer, 0, customers_num * sizeof(int));
    individual->Transfer_Car_Capacities_Free = (int*)malloc(Fixed_Route_individual->vehicles_num_K * sizeof(int));
    /*individual->Customer_Transfer[1] = 1;
    individual->Customer_Transfer[2] = 1;
    individual->Customer_Transfer[5] = 1;
    individual->Customer_Transfer[9] = 1;
    individual->Customer_Transfer[10] = 1;
    individual->Customer_Transfer[11] = 1;
    individual->Customer_Transfer[13] = 1;
    individual->Customer_Transfer[15] = 1;*/


    individual->cloned = 0;
    individual->vehicles_num_K = vehicles_num;
    individual->Transfer_Car_Number = 0;
    //individual->Transfer_Car_Number = 3;//測試用
    /*Transfer_Car_Totol_Capacities_Free計算和individual->Transfer_Car_Capacities_Free[]*/
    int temp = 0;
    for (int i = 0; i < Fixed_Route_individual->vehicles_num_K;i++) {
        individual->Transfer_Car_Capacities_Free[i] = Fixed_Route_individual->capacities_free[i];
        temp += Fixed_Route_individual->capacities_free[i];
    }
    individual->Transfer_Car_Totol_Capacities_Free = temp;
    /*Transfer_Car_Totol_Capacities_Free計算和individual->Transfer_Car_Capacities_Free[]*/

    return individual;
}
Individual* Fixed_Route_individual_init(int customers_num, int vehicles_num) {//定義與初始化individual

    Individual* individual = (Individual*)malloc(sizeof(Individual));
    individual->routes = (int**)malloc(vehicles_num * sizeof(int*));

    for (int i = 0; i < vehicles_num; i++) {
        individual->routes[i] = (int*)malloc(customers_num * sizeof(int));
    }

    individual->positions = (int**)malloc(2 * sizeof(int*));
    individual->positions[0] = (int*)malloc(customers_num * sizeof(int));
    individual->positions[1] = (int*)malloc(customers_num * sizeof(int));
    /*每個顧客 i 的位置都是由 positions[i][...] 來表示的。
    positions[0][i] 表示第 i 個顧客所在的路線編號。
    positions[1][i] 表示第 i 個顧客在其所屬路線中的索引或位置。
    舉例來說，如果 positions[0][5] 的值是 3，並且 positions[1][5] 的值是 7，這表示第5個顧客在第3條路線中，並且他是這條路線的第7個顧客。*/

    //設定場站position
    individual->positions[0][0] = individual->positions[1][0] = 0;

    individual->routes_end = (int*)malloc(vehicles_num * sizeof(int));
    individual->capacities_free = (int*)malloc(vehicles_num * sizeof(int));

    individual->Customer_Transfer = (int*)malloc(customers_num * sizeof(int));
    //individual->Transfer_Car_Capacities_Free = (int*)malloc(Fixed_Route_individual_K * sizeof(int));

    individual->cloned = 0;
    individual->vehicles_num_K = vehicles_num;
    individual->Transfer_Car_Number = 0;
    individual->Transfer_Car_Totol_Capacities_Free = 0;

    return individual;
}

Individual* individual_free(Individual* individual, int vehicles_num) {
    for (int i = 0; i < vehicles_num; i++) {
        free(individual->routes[i]);
    }
        
    free(individual->routes);
    
    free(individual->capacities_free);
    free(individual->positions[0]);
    free(individual->positions[1]);
    free(individual->positions);
    
    free(individual->routes_end);

    free(individual->Customer_Transfer);
    free(individual->Transfer_Car_Capacities_Free);


    free(individual);

    return NULL;
}


Individual* individual_generate_top_to_down(int** distances, Customer* customers, int customers_num, int capacity_max, int vehicles_num, Individual* Fixed_Route_individual,int transfer_cost_once) {
    int load = 0,
        random = 0,
        route_load = 0;
    //此顧客有無檢查過，不論他們是否被成功分配到路徑中
    int* customers_checked = new int[customers_num];
    //此顧客有無插入到路徑中的標記
    int* customers_routed = new int[customers_num];
    
    // memset 將一塊記憶體區域的內容設定為給定的值 (初始customers_checked和customers_routed)
    //將 customers_checked 陣列的每個元素都初始化（或重設）為0
    memset(customers_checked, 0, customers_num*sizeof(int));
    //將 customers_routed 陣列的每個元素都初始化（或重設）為0
    memset(customers_routed, 0,  customers_num*sizeof(int));
    customers_checked[0] = 1;
    customers_routed[0] = 1;
    
    //定義與初始化individual
    Individual* individual = individual_init(customers_num, vehicles_num, Fixed_Route_individual);
    //路徑中第幾個位置(從0開始)
    int index = 0,
        //目前共檢查幾個顧客
        customers_checked_cnt = 1,
        //目前全部路徑上共有幾個顧客
        customers_routed_cnt = 1;
    //第幾條路徑(從0開始)
    int routes_planned_cnt;
    //一條一條路徑插入執行
    for (routes_planned_cnt = 0; routes_planned_cnt < vehicles_num; routes_planned_cnt++) {
        //當前路徑累加需求
        route_load = 0;
        do {
            do {
                random = (rand() % (customers_num-1)) +1; //+1 因為場站是0; 顧客點位為 1-31.
            }
            //直到random到沒有被檢查過的顧客
            while (customers_checked[random]);
            //此顧客需求
            load = customers[random].demand;
            //將需求累加到路徑上
            route_load += load;
            //如果累加後沒有超過車輛重量限制
            if (route_load < capacity_max) {
                //將此顧客加入路線
                individual->routes[routes_planned_cnt][index] = random;
                individual->positions[0][random] = routes_planned_cnt;
                individual->positions[1][random] = index;
                //更新此顧客有插入到路徑中的標記
                customers_routed[random] = 1;
                //累加全部路徑上共有幾個顧客
                customers_routed_cnt++;
                //換路徑中第下一個位置(從0開始)
                index++;
                
            } 
            //加入此顧客會超過車輛限重
            else {
                //減去此顧客重量，並不做其他動作
                route_load = route_load - load;
            }
            //更新此顧客有檢查過
            customers_checked[random] = 1;
           
            //更新目前共檢查幾個顧客
            customers_checked_cnt++;
            
        }  
        //判斷是否已經全部顧客皆檢查過(沒有就持續做下去)
        while (customers_checked_cnt < customers_num);
        //getchar();
        //全部顧客皆檢查過後，初始化customers_checked_cnt
        customers_checked_cnt = 1;
        //TODO:check下面for是否多餘
        for (int i = 1; i < customers_num; i++) {
            //如果此顧客有被插入路徑中
            if (customers_routed[i]) {
                //更新此顧客有檢查過
                customers_checked[i] = 1;
                //更新目前共檢查幾個顧客
                customers_checked_cnt++;
            } 
            //此顧客沒有被檢查過
            else { 
                //更新此顧客沒有檢查過
                customers_checked[i] = 0;
            }
        }
        //當前routes_planned_cnt路徑中有幾個顧客
        individual->routes_end[routes_planned_cnt] = index;
        //重製路徑位置
        index = 0;

        // 檢查是否所有客戶都已經被分配
        if (customers_routed_cnt == customers_num) {
            routes_planned_cnt++;
            while (routes_planned_cnt < vehicles_num) {
                individual->routes_end[routes_planned_cnt] = index;
                routes_planned_cnt++;
            }
            routes_planned_cnt--;//要避免超過範圍
            break;  // 跳出for循環
        }

    }
    //檢查個體的可行性
        //判斷目前全部路徑上是否有全部顧客
    if (customers_routed_cnt == customers_num) {
        //更新個體資訊與成本(違反重量限制會加上逞罰成本)
        individual_reevaluate(individual, capacity_max, vehicles_num, distances, customers, Fixed_Route_individual, transfer_cost_once);
        return individual;
    }
    
    /*如果還有客戶沒有被分配到某條路線，他們將被加入到最後一條路線(上面超過重量的顧客)*/
    //減一 因為每次執行完後會加一，但要加入最後一條而不是新的一條
    routes_planned_cnt--;
    //從最後的位置開始加(因為從index從0開始，但最後都會加一來配合有幾個顧客，所以剛好是從最後一條路徑有幾個顧客當作index，作為下一個要放的index)
    index = individual->routes_end[routes_planned_cnt];
    
    for (int i = 1; i < customers_num; i++) {
        //如果沒有被插入路徑中
        if(!customers_routed[i]) {
            //將其插入
            individual->routes[routes_planned_cnt][index] = i;
            individual->positions[0][i] = routes_planned_cnt;
            individual->positions[1][i] = index;
            //換路徑中第下一個位置
            index++;
        }
    }
    //更新此路徑共有幾個顧客
    individual->routes_end[routes_planned_cnt] = index;
    //更新個體資訊與成本(違反重量限制會加上逞罰成本)
    individual_reevaluate(individual, capacity_max, vehicles_num, distances, customers, Fixed_Route_individual, transfer_cost_once);

    return individual;
}


//TODO: make top to down and down to top in the same function
Individual* individual_generate_down_to_top(int** distances, Customer* customers, int customers_num, int capacity_max, int vehicles_num, Individual* Fixed_Route_individual, int transfer_cost_once) {
    int load = 0,
        random = 0,
        route_load = 0;
        
    int* customers_checked = new int[customers_num];
    int*  customers_routed = new int[customers_num];
        
    memset(customers_checked, 0, customers_num*sizeof(int));
    memset(customers_routed, 0,  customers_num*sizeof(int));
    customers_checked[0] = 1;
    customers_routed[0] = 1;
    
    Individual* individual = individual_init(customers_num, vehicles_num, Fixed_Route_individual);
    
    int index = 0,
        customers_checked_cnt = 1,
        customers_routed_cnt = 1;
    
    int routes_planned_cnt;
    for (routes_planned_cnt = vehicles_num -1; routes_planned_cnt >= 0; routes_planned_cnt--) {
    
        route_load = 0;
        do {
            do {
                random = (rand() % (customers_num-1)) +1; //+1 pois 0 é o posto; raio 1-31.
            } while (customers_checked[random]);

            load = customers[random].demand;
            route_load = route_load + load;

            if (route_load < capacity_max) {
                individual->routes[routes_planned_cnt][index] = random;
                individual->positions[0][random] = routes_planned_cnt;
                individual->positions[1][random] = index;

                customers_routed[random] = 1;
                customers_routed_cnt++;
                index++;

            } else {
                route_load = route_load - load;
            }
        
            customers_checked[random] = 1;
            customers_checked_cnt++;
        } while (customers_checked_cnt < customers_num);
        
        customers_checked_cnt = 1;
        for (int i = 1; i < customers_num; i++) {
            if (customers_routed[i]) {
                customers_checked[i] = 1;
                customers_checked_cnt++;
                
            } else {
                customers_checked[i] = 0;
            }
        }

        individual->routes_end[routes_planned_cnt] = index;
        index = 0;

        if (customers_routed_cnt == customers_num) {
            routes_planned_cnt--;
            while (routes_planned_cnt >= 0) {
                individual->routes_end[routes_planned_cnt] = index;
                routes_planned_cnt--;
            }
            routes_planned_cnt++;//要避免超過範圍
            break;  // 跳出for循環
        }

    }
    
    //Verificando viabilidade do individual.
    if (customers_routed_cnt == customers_num) {
        individual_reevaluate(individual, capacity_max, vehicles_num, distances, customers,Fixed_Route_individual, transfer_cost_once);
        return individual;
    }
    
    /* Caso ainda existam customers que não foram alocadas em alguma route, elas serão inseridas na primeira route */
    routes_planned_cnt++;
    index = individual->routes_end[routes_planned_cnt];
    
    for (int i = 1; i < customers_num; i++) {
        if(!customers_routed[i]) {
            individual->routes[routes_planned_cnt][index] = i;
            individual->positions[0][i] = routes_planned_cnt;
            individual->positions[1][i] = index;
            
            index++;
        }
    }
    
    individual->routes_end[routes_planned_cnt] = index; 
    individual_reevaluate(individual, capacity_max, vehicles_num, distances, customers, Fixed_Route_individual, transfer_cost_once);

    return individual;
}
        

void individual_reevaluate(Individual* individual, int capacity_max, int vehicles_num, int** distances, Customer* customers, Individual* Fixed_Route_individual, int transfer_cost_once) {//更新個體資訊與成本
    //路徑i
    int *route = NULL;
         
    int cost = 0,
        route_load = 0,//累加路徑i重量
        component = 0,//路徑i中的第j個位址顧客
        customer_current = 0,
        customer_before = 0;
    int total_transfer_capacities=0;//總轉移容量
        
    individual->feasible = 1;
    individual->cost = 0;

    //路徑i有多少顧客
    int route_end;
    //重整轉移路線空閒容量
    for (int i = 0; i < Fixed_Route_individual->vehicles_num_K;i++) {
        individual->Transfer_Car_Capacities_Free[i] = Fixed_Route_individual->capacities_free[i];
    }
//更新個體資訊與成本
    //每一條路線執行一次
    for (int i = 0; i < vehicles_num; i++) {
    
        //路徑i
        route = individual->routes[i];
        //路徑i有多少顧客
        route_end = individual->routes_end[i];
        route_load = 0;
        for (int j = 0; j < route_end; j++) {
            //路徑i中的第j個位址顧客
            component = route[j];
            //累加路徑i重量
            //printf("individual->Customer_Transfer[%d]=%d\n",component, individual->Customer_Transfer[component]);
            //判斷顧客是否轉移
            if (individual->Customer_Transfer[component] == 0) {
                route_load += customers[component].demand;
                //printf("有被算入容量的customer=>  %d\n",component);
            }
            else {
                //該路線被放入容量要減
                individual->Transfer_Car_Capacities_Free[Fixed_Route_individual->positions[0][component]] -= customers[component].demand;
                //總轉移容量也要減
                total_transfer_capacities+= customers[component].demand;
            }
            
        }
        
        //printf("\n");
        //計算路徑i剩餘空間
        individual->capacities_free[i] = capacity_max - route_load;
        //printf("individual->capacities_free[%d]=    %d\n",i, individual->capacities_free[i]);
        

        //超過車輛容量上限
        if (route_load > capacity_max && individual->feasible) {
            //更新不符合重量限制
            individual->feasible = 0;
            //適應值加上逞罰成本
            individual->cost += PENALTY;
        }
        
        //計算成本
        //每條路徑第一個0
        customer_before = 0;
        cost = 0;
        for (int j = 0; j < route_end; j++) {
            if (individual->Customer_Transfer[route[j]]!=0) {
                continue;
            }
            customer_current = route[j]; 
            //前後顧客成本
            cost += distances[customer_before][customer_current];
            customer_before = customer_current;
        }
        //每條路徑最後一個0
        cost += distances[customer_before][0];
        //for加到最後即全部成本(全部路徑)
        individual->cost += cost;
    }
    //計算總轉移車輛
    double temp = (total_transfer_capacities * 1.0) / capacity_max;
    if (temp - (int)temp != 0) {
        //具有小數部分
        individual->Transfer_Car_Number =  temp+ 1;
    }
    else {
        //整數
        individual->Transfer_Car_Number = temp;
    }
        //計算總轉移車輛空閒空間
    individual->Transfer_Car_Totol_Capacities_Free = (individual->Transfer_Car_Number * capacity_max) - total_transfer_capacities;
    //加上轉移成本
    individual->cost += (individual->Transfer_Car_Number * transfer_cost_once);

    return;
}


/* Não são clonadas as cargas disponiveis */
Individual* individual_make_hard_clone(Individual* individual, int customers_num, int vehicles_num, Individual* Fixed_Route_individual) {
    Individual* clone = individual_init(customers_num, vehicles_num, Fixed_Route_individual);
    
    int route_end = 0;
    for (int i = 0; i < individual->vehicles_num_K; i++) {
        route_end = individual->routes_end[i];

        clone->routes_end[i] = route_end;
        for (int j = 0; j < route_end; j++)
            clone->routes[i][j] = individual->routes[i][j];
    }
    
    for (int j = 0; j < customers_num; j++) {
        clone->positions[0][j] = individual->positions[0][j];
        clone->positions[1][j] = individual->positions[1][j];
    }

    for (int i = 0; i < customers_num;i++) {
        clone->Customer_Transfer[i] = individual->Customer_Transfer[i];
    }
    for (int i = 0; i < Fixed_Route_individual->vehicles_num_K;i++) {
        clone->Transfer_Car_Capacities_Free[i] = individual->Transfer_Car_Capacities_Free[i];
    }
    clone->Transfer_Car_Number = individual->Transfer_Car_Number;
    clone->Transfer_Car_Totol_Capacities_Free = individual->Transfer_Car_Totol_Capacities_Free;

    clone->cost = individual->cost;
    clone->feasible = individual->feasible;
    clone->vehicles_num_K = individual->vehicles_num_K;

    return clone;
}


/* Deve ser inserido em outra route */
void individual_insert_customer(Individual* individual, int customer, int load, int new_idx, int new_route) {
    int *route = individual->routes[new_route],
         position = individual->routes_end[new_route];
    
    int customer_chosen = -1;
    //當要插入之位置超過當前最多顧客數量
    while (position > new_idx) {
        //插入到當前路線指定位置前一位，直至當前路線最後一位顧客後面一位
        customer_chosen = route[position -1];
        route[position] = customer_chosen;
        individual->positions[1][customer_chosen]++;
        position--;
    }
    
    individual->positions[0][customer] = new_route;
    route[position] = customer;
    individual->positions[1][customer] = position;
    individual->routes_end[new_route]++;
    if (individual->Customer_Transfer[customer]==0) {
        individual->capacities_free[new_route] -= load;
        if (individual->capacities_free[new_route] < 0) {
            //individual->feasible = 0;
        }
    }

    return;
}


void individual_reinsert_customer_in_route(Individual* individual, int customer, int new_idx) {
    int *route = individual->routes[ individual->positions[0][customer] ],
         position = individual->positions[1][customer];

    int customer_chosen = -1;
    if (new_idx < position) {
        while (position > new_idx) {
            customer_chosen = route[position -1];
            route[position] = customer_chosen;
            individual->positions[1][customer_chosen]++;
            position--;
        }
        
        route[position] = customer;
        individual->positions[1][customer] = position;
        return;
    }
    
    new_idx--;
    while (position < new_idx) {
        customer_chosen = route[position +1];
        route[position] = customer_chosen;
        individual->positions[1][customer_chosen]--;
        position++;
    }
    
    route[position] = customer;
    individual->positions[1][customer] = position;

    return;
}


/* Sem uso
void individual_insere_cidade_fim_rota(Individual* individual, int customer, int load, int route) {
    int index = individual->routes_end[route];
    individual->routes_end[route]++;

    individual->capacities_free[route] -= load;
    individual->routes[route][index] = customer;
    individual->positions[0][customer] = route;
    individual->positions[1][customer] = index;
    return;
}*/


/* Se as customers estiverem na mesma route, passar as cargas como 0 pois não mudarão */
void individual_swap_customers(Individual* individual, int customer1, int load1, int customer2, int load2) {
    int rota1 =    individual->positions[0][customer1],
        posicao1 = individual->positions[1][customer1],
        rota2 =    individual->positions[0][customer2],
        posicao2 = individual->positions[1][customer2];
    if (individual->Customer_Transfer[customer1] == 1) {
        load1 = 0;
    }
    if (individual->Customer_Transfer[customer2] == 1) {
        load2 = 0;
    }

    individual->routes[rota2][posicao2] = customer1;
    individual->routes[rota1][posicao1] = customer2;
    
    individual->positions[0][customer2] = rota1;
    individual->positions[1][customer2] = posicao1;
    
    individual->capacities_free[rota1] = individual->capacities_free[rota1] + load1 - load2;

    individual->positions[0][customer1] = rota2;
    individual->positions[1][customer1] = posicao2;
    individual->capacities_free[rota2] = individual->capacities_free[rota2] - load1 + load2;

    return;
}


void individual_remove_customer(Individual* individual, int customer, int load) { //TODO: pass customer instead
    int  route_idx = individual->positions[0][customer],
         route_end = individual->routes_end[route_idx],
         index = individual->positions[1][customer];
    if (individual->Customer_Transfer[customer]==0) {
        individual->capacities_free[route_idx] += load;
    }
    individual->routes_end[route_idx]--;
    
    //Se a customer a ser removida é a última customer da route.
    if (index +1 == route_end) {
        return;
    }
    
    int *route = individual->routes[route_idx],
         customer_new = 0;
    while (index < route_end -1) {
        customer_new =  route[index +1];
        route[index] = customer_new;
        individual->positions[1][customer_new] = index;
        index++;
    }

    return;
}
