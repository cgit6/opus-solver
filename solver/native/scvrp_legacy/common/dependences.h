#ifndef DEPENDENCES_H
#define DEPENDENCES_H

typedef struct customer Customer;

struct customer {
    int id,     /* Customer number */
        demand; /* Customer demand */
    double x,y; /* Customer 2D position */
};


typedef struct individual Individual;

struct individual {
    int** routes,       /* Matrix of vector, each vector represents a route *///這是一個二維整數指標，它可以指向一個整數矩陣。每個矩陣中的向量表示一條路線routes[哪一條][哪個位置]
        ** positions,    /* 2D vector. Each index i presents the position of the customer i in routes. First vector presents the route number and second presents the route index *///每個索引i代表顧客i在routes中的位置。第一個向量表示路線編號，第二個表示路線索引
                        /*每個顧客 i 的位置都是由 positions[i][...] 來表示的。
                        positions[0][i] 表示第 i 個顧客所在的路線編號。
                        positions[1][i] 表示第 i 個顧客在其所屬路線中的索引或位置。
                        舉例來說，如果 positions[0][5] 的值是 3，並且 positions[1][5] 的值是 7，這表示第5個顧客在第3條路線中，並且他是這條路線的第7個顧客。*/
        * routes_end,   /* Number of customers each route contains *///該陣列表示每條路線包含的顧客數
        * capacities_free,  /* Available load/demand each route/vehicle has *///這個陣列表示每條路線（或車輛）的可用負載/需求
        * Customer_Transfer,//每個顧客轉移與否，0不轉，1轉移
        * Transfer_Car_Capacities_Free;//每條固定路線空閒容量
    int cost;           /* Individual cost/objective function *///表示個體的成本或目標函數值
    int feasible;       /* A flag to represent if the individual is feasible */ //TODO: make enum?//用作標誌，表示該個體是否可行
    int cloned;         /* A flag to represent if the individual is cloned */ //TODO: define cloned better; SOFT CLONE AND HARD CLONE//表示該個體是否已被克隆
    int vehicles_num_K;
    int Transfer_Car_Number;//轉移車輛數
    int Transfer_Car_Totol_Capacities_Free;//總轉移車輛剩餘空間
};


typedef struct header Header;

struct header {
    int capacity_max,
        vehicles_num,
        customers_num, 
        best_solution_value;
};

typedef struct sa SA;
struct sa {
    double startTemp = 1.0;
    double endTemp = 0.01;
    double coolingRate = 0.95;
    int maxIterations = 110;//110
};


Customer* customer_free(Customer* customer);

int** distances_matrix_init(Customer* customers, int customers_num);

int** distances_matrix_free(int** distances, int customers_num);

double calculate_transfer_cost(int** distances, int customers_num);

//int calculate_distance(Customer* c1, Customer* c2);


Individual* individual_init(int customers_num, int vehicles_num,Individual* Fixed_Route_individual);
Individual* Fixed_Route_individual_init(int customers_num, int vehicles_num);

Individual* individual_free(Individual* individuo, int vehicles_num);

Individual* individual_generate_top_to_down(int** distances, Customer* customers, int customers_num, int capacity_max, int vehicles_num, Individual* Fixed_Route_individual, int transfer_cost_once);

Individual* individual_generate_down_to_top(int** distances, Customer* customers, int customers_num, int capacity_max, int vehicles_num, Individual* Fixed_Route_individual, int transfer_cost_once);

void individual_swap_customers(Individual* individual, int customer1, int load1, int customer2, int load2);

void individual_reinsert_customer_in_route(Individual* individual, int customer, int new_idx);

void individual_insert_customer(Individual* individual, int customer, int load, int new_idx, int new_route);

void individual_remove_customer(Individual* individual, int customer, int load);

void individual_reevaluate(Individual* individual, int capacity_max, int vehicles_num, int** distances, Customer* customers,Individual* Fixed_Route_individual,int transfer_cost_once);

Individual* individual_make_hard_clone(Individual* individual, int customers_num, int vehicles_num, Individual* Fixed_Route_individual);


#endif /* DEPENDENCES_H */
