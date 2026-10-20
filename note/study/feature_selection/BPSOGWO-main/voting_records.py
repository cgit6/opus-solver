import numpy as np
import pandas as pd
from sklearn import preprocessing

from algorithm import BGWO
from algorithm import BGWO2
from algorithm import BPSOGWO
from algorithm import BPSO

#导入数据
data = pd.read_table("data/Voting Records/house-votes-84.data", header=None, delimiter=",") #(435,17)

#处理缺失数据
drop = []
for i in range(len(data)):
    for c in data.columns:
        if data[c][i] == '?':
            drop.append(i)
data = data.drop(drop) #(232,17)


#标签数值化
le = preprocessing.LabelEncoder()
for feature in data.columns:
    le.fit(data[feature])
    data[feature] = le.transform(data[feature])

data = np.array(data, 'float')
label = data[:,0]
feature = data[:,1:]
n_feature = feature.shape[1]

subset = []
for i in range(n_feature):
    subset.append(i)
print("原数据集error：", 1-BGWO.acc_score(subset, fold=2, neighbors=5, feature=feature, label=label))

fitness = np.zeros((10,23))
error = np.zeros((10,23))
num = np.zeros((10,23))

fitness[0], error[0], num[0] = BGWO.cal(feature, label, times=20, iter=70, a=0, trans='s', initialization=0, b=0.01) #BGWO
fitness[1], error[1], num[1] = BGWO.cal(feature, label, times=20, iter=70, a=1, trans='s', initialization=0, b=0.01) #ABGWO
fitness[2], error[2], num[2] = BGWO.cal(feature, label, times=20, iter=70, a=1, trans='v1a', initialization=0, b=0.01) #ABGWO_V1a
fitness[3], error[3], num[3] = BGWO.cal(feature, label, times=20, iter=70, a=1, trans='v2a', initialization=0, b=0.01) #ABGWO_V2a
fitness[4], error[4], num[4] = BGWO2.cal(feature, label, times=20, iter=70, initialization=0, b=0.01) #BGWO2
fitness[5], error[5], num[5] = BPSO.cal(feature, label, times=20, iter=70, initialization=0, b=0.01) #BPSO
fitness[6], error[6], num[6] = BPSOGWO.cal(feature, label, times=20, iter=70, a=0, trans='s', initialization=0, b=0.01) #PSO_BGWO
fitness[7], error[7], num[7] = BPSOGWO.cal(feature, label, times=20, iter=70, a=1, trans='s', initialization=0, b=0.01) #PSO_ABGWO
fitness[8], error[8], num[8] = BPSOGWO.cal(feature, label, times=20, iter=70, a=1, trans='v1a', initialization=0, b=0.01) #PSO_ABGWO_V1a
fitness[9], error[9], num[9] = BPSOGWO.cal(feature, label, times=20, iter=70, a=1, trans='v2a', initialization=0, b=0.01) #PSO_ABGWO_V2a

np.savetxt('result/voting_records_fitness.csv', fitness.T, fmt='%.4f', delimiter=',')
np.savetxt('result/voting_records_error.csv', error.T, fmt='%.4f', delimiter=',')
np.savetxt('result/voting_records_num.csv', num.T, fmt='%.4f', delimiter=',')