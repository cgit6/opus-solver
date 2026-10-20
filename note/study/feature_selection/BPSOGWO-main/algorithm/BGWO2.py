import numpy as np
from sklearn.neighbors import KNeighborsClassifier
from sklearn.model_selection import StratifiedKFold
import random

#精确度计算
def acc_score(subset, fold, neighbors, feature, label):
    sub_feature = feature[:,subset]
    kf = StratifiedKFold(n_splits=fold, shuffle=True, random_state=0)
    predict = np.zeros(sub_feature.shape[0])
    for train_index, test_index in kf.split(sub_feature, label):
        knn = KNeighborsClassifier(n_neighbors=neighbors).fit(sub_feature[train_index], label[train_index])
        predict[test_index] = knn.predict(sub_feature[test_index])
    acc = np.mean(predict == label)
    return acc

#Fitness函数
def F1(subset, b, feature, label):
    n_feature = feature.shape[1]
    subset_list = []
    for i in range(len(subset)):
        if subset[i] == 1:
            subset_list.append(i)
    if len(subset_list) == 0:
        return 1.0
    score1 = 1 - acc_score(subset_list, fold=2, neighbors=5, feature = feature, label = label)
    score2 = len(subset_list) / n_feature
    score = (1-b) * score1 + b * score2
    return score

#二进制灰狼算法
def GWO(fitness, dim, SearchAgents_no, Max_iter, feature, label, initialization = 1, b = 0.01):
    #初始化Alpha、Beta、Delta
    Alpha_pos = np.zeros(dim)
    Alpha_score = 1
    Beta_pos = np.zeros(dim)
    Beta_score = 1
    Delta_pos = np.zeros(dim)
    Delta_score = 1

    #初始化所有狼的位置
    if initialization == 0: #小初始化
        Positions = np.random.randint(0, 8, (SearchAgents_no, dim), dtype='int')
        Positions[Positions > 1] = 0
    else:
        Positions = np.random.randint(0, 2, (SearchAgents_no, dim), dtype='int')  # 随机生成0/1矩阵

    #迭代
    for l in range(0, Max_iter):
        for i in range(0, SearchAgents_no):
            Fitness = fitness(Positions[i, :], b, feature, label)
            if Fitness < Alpha_score:
                Delta_pos = Beta_pos.copy()
                Delta_score = Beta_score
                Beta_pos = Alpha_pos.copy()
                Beta_score = Alpha_score
                Alpha_pos = Positions[i].copy()
                Alpha_score = Fitness
            elif Fitness > Alpha_score and Fitness < Beta_score:
                Delta_pos = Beta_pos.copy()
                Delta_score = Beta_score
                Beta_pos = Positions[i].copy()
                Beta_score = Fitness
            elif Fitness > Alpha_score and Fitness > Beta_score and Fitness < Delta_score:
                Delta_pos = Positions[i].copy()
                Delta_score = Fitness

        a = 2 - 2 * l / Max_iter

        for i in range(0, SearchAgents_no):
            for j in range(0, dim):
                r1 = random.random()  # 生成0-1的随机浮点数
                r2 = random.random()
                A1 = 2 * a * r1 - a
                B1 = 2 * r2

                D_alpha = abs(B1 * Alpha_pos[j] - Positions[i, j])
                X1 = Alpha_pos[j] - A1 * D_alpha

                r1 = random.random()
                r2 = random.random()
                A2 = 2 * a * r1 - a
                B2 = 2 * r2

                D_beta = abs(B2 * Beta_pos[j] - Positions[i, j])
                X2 = Beta_pos[j] - A2 * D_beta

                r1 = random.random()
                r2 = random.random()
                A3 = 2 * a * r1 - a
                B3 = 2 * r2

                D_delta = abs(B3 * Delta_pos[j] - Positions[i, j])
                X3 = Delta_pos[j] - A3 * D_delta

                #BGWO2
                r3 = random.random()
                temp = (X1 + X2 + X3) / 3
                X = 1 / (1 + np.exp(-10 * (temp - 0.5))) #sigmoid

                if X > r3:
                    Positions[i, j] = 1
                else:
                    Positions[i, j] = 0

    subset = []
    for i in range(len(Alpha_pos)):
        if Alpha_pos[i] == 1:
            subset.append(i)
    min_error = 1 - acc_score(subset, fold=2, neighbors=5, feature = feature, label = label)
    feature_num = sum(Alpha_pos == 1)
    print(Alpha_score, min_error, feature_num)
    return Alpha_score, min_error, feature_num

def cal(feature, label, times=20, iter=70, initialization = 1, b = 0.01):
    n_feature = feature.shape[1]
    score = np.zeros(times + 3)
    error = np.zeros(times+ 3)
    num = np.zeros(times + 3)
    str = "BGWO2"
    print(str+":")
    for i in range(times):
        score[i], error[i], num[i] = GWO(fitness=F1, dim=n_feature, SearchAgents_no=8, Max_iter=iter,
                                         feature=feature, label=label,
                                         initialization = initialization, b = b)
    print(str + " mean result:", score[:times].mean(), error[:times].mean(), num[:times].mean())
    score[times], error[times], num[times] = score[:times].mean(), error[:times].mean(), num[:times].mean()
    min_score_index = np.argsort(score[:times])[0]
    print(str + " best result:", score[:times][min_score_index], error[:times][min_score_index], num[:times][min_score_index])
    score[times + 1], error[times + 1], num[times + 1] = score[:times][min_score_index], error[:times][min_score_index], num[:times][min_score_index]
    max_score_index = np.argsort(score[:times])[-1]
    print(str + " worst result:", score[:times][max_score_index], error[:times][max_score_index], num[:times][max_score_index])
    score[times + 2], error[times + 2], num[times + 2] = score[:times][max_score_index], error[:times][max_score_index], num[:times][max_score_index]
    return score, error, num #前20为每次运行结果，21为平均，22为最优，23为最坏