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

def sigmoid_(x):
    y = 1 / (1 + np.exp(-x))
    if y >= random.random():
        return 1
    else:
        return 0

def PSO(fitness, dim, SearchAgents_no, Max_iter, feature, label, initialization = 1, b = 0.01):
    #初始化所有狼的位置
    if initialization == 0: #小初始化
        Positions = np.random.randint(0, 8, (SearchAgents_no, dim), dtype='int')
        Positions[Positions > 1] = 0
    else:
        Positions = np.random.randint(0, 2, (SearchAgents_no, dim), dtype='int')  # 随机生成0/1矩阵

    velocity = np.random.random((SearchAgents_no, dim))
    c = 0.5

    pBestScore = np.ones((SearchAgents_no))
    pBest = np.zeros((SearchAgents_no, dim))
    gBestScore = 1
    gBest = np.zeros((dim))

    #迭代
    for l in range(0, Max_iter):
        for i in range(0, SearchAgents_no):
            Fitness = fitness(Positions[i, :], b, feature, label)
            if Fitness < pBestScore[i]:
                pBestScore[i] = Fitness
                pBest[i, :] = Positions[i, :].copy()

            if Fitness < gBestScore:
                gBestScore = Fitness
                gBest = Positions[i, :].copy()

        w = 0.5 + random.random() / 2

        for i in range(0, SearchAgents_no):
            for j in range(0, dim):
                r1 = random.random()
                r2 = random.random()
                velocity[i,j] = w * velocity[i,j] + c * r1 * (pBest[i, j] - Positions[i, j]) + c * r2 * (gBest[j] - Positions[i, j])
                if sigmoid_(velocity[i,j]) == 1:
                    Positions[i,j] = 1
                else:
                    Positions[i,j] = 0

    subset = []
    for i in range(len(gBest)):
        if gBest[i] == 1:
            subset.append(i)
    if len(subset) == 0:
        min_error = 0
    else:
        min_error = 1 - acc_score(subset, fold=2, neighbors=5, feature = feature, label = label)
    feature_num = sum(gBest == 1)
    print(gBestScore, min_error, feature_num)
    return gBestScore, min_error, feature_num

def cal(feature, label, times=20, iter=70, initialization = 1, b = 0.01):
    n_feature = feature.shape[1]
    score = np.zeros(times + 3)
    error = np.zeros(times+ 3)
    num = np.zeros(times + 3)
    str = "BPSO"
    print(str+":")
    for i in range(times):
        score[i], error[i], num[i] = PSO(fitness=F1, dim=n_feature, SearchAgents_no=8, Max_iter=iter,
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

