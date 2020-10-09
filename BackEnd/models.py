# -*- coding: utf-8 -*-
import torch
import torch.nn.functional as F
import numpy as np
import sklearn

#from ceml.torch import generate_counterfactual
from ceml.sklearn import generate_counterfactual
from ceml.backend.torch.costfunctions import SquaredError
from ceml.model import ModelWithLoss

# Neural network - Linear regression
class Model(torch.nn.Module, ModelWithLoss):
    def __init__(self, input_size):
        super(Model, self).__init__()
        self.linear1 = torch.nn.Linear(input_size, 200)
        self.linear2 = torch.nn.Linear(200, 100)
        self.linear3 = torch.nn.Linear(100, 1)

    def forward(self, x):
        x = torch.Tensor(x).double()
        x = F.leaky_relu(self.linear1(x))
        x = F.leaky_relu(self.linear2(x))

        return self.linear3(x)

    def predict(self, x, dim=1):
        return self.forward(x)

    def get_loss(self, y_target, pred=None):
        return SquaredError(input_to_output=self.predict, y_target=y_target)


# Load stored model parameters
def load_model_from_file(file_path='modelsStuff/PyTorchNetDataSet1_Regression_500epochs_SquaredError.joblib'):
#def load_model_from_file(file_path='modelsStuff/PyTorchNetDataSet1_Regression_2000epochs_SquaredError.joblib'):
    return torch.load(file_path)

# Fit model
def build_model(file_path="modelsStuff/AlienZooDataSet1.csv"):
    import pandas as pd
    from sklearn.tree import DecisionTreeRegressor
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import mean_squared_error, r2_score

    df = pd.read_csv(file_path)

    df = df[["Var1", "Var2", "Var3", "Var4", "Var5", "GR"]]
    X = df[["Var1", "Var2", "Var3", "Var4", "Var5"]].to_numpy()
    y = df["GR"].to_numpy()

    print(X.shape)
    print(y.shape)

    # Split into training and test set
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.33, random_state=42)

    # Fit model
    model = DecisionTreeRegressor(max_depth=4, random_state=42)
    model.fit(X_train, y_train)

    # Evaluate
    y_pred = model.predict(X_test)
    print(f"R^2: {r2_score(y_test, y_pred)}")
    print(f"MSE: {mean_squared_error(y_test, y_pred)}")
    
    return model


# Compute counterfactual
def get_leafs_from_tree(tree_, classifier=False):
    leafs = []
    def traversal(node, path):
        if tree_.feature[node] != sklearn.tree._tree.TREE_UNDEFINED:
            feature_id = tree_.feature[node]
            threshold = tree_.threshold[node]

            traversal(tree_.children_left[node], path + [(node, feature_id, threshold, "<")])
            traversal(tree_.children_right[node], path + [(node, feature_id, threshold, ">")])
        else:
            if classifier is False:
                path += [(node, -1, tree_.value[node].flatten()[0])]
            else:
                path += [(node, -1, np.argmax(tree_.value[node]))]
            leafs.append(path)

    traversal(0, [])

    return leafs

def leaf_to_path(path_to_leaf):
    return [p[0] for p in path_to_leaf]


def compute_overlap_of_path(p1, p2):
    if p1 == [] or p2 == []:
        return 0
    if p1[0] != p2[0]:
        return 0
    else:
        return 1 + compute_overlap_of_path(p1[1:], p2[1:])


def compute_change(x, threshold, direction):
    eps = 1.e-5

    if direction == "<":
        if x >= threshold:
            return -1. * np.abs(threshold - x) - eps
        else:
            return 0
    elif direction == ">":
        if x <= threshold:
            return np.abs(threshold - x) + eps
        else:
            return 0


def compute_path_adjustment(x_orig, x_orig_path, target_path):
    r = {}
    overlap = 0
    y = target_path[-1][2]

    for i in range(len(target_path) - 1):
        if x_orig_path[i+1] != target_path[i+1][0]: # Starting point found?
            for j in range(i, len(target_path) - 1):
                feature_id = target_path[j][1]
                threshold = target_path[j][2]
                direction = target_path[j][3]
                x = x_orig[feature_id]

                delta = compute_change(x, threshold, direction)
                if delta != 0:
                    if feature_id in r:
                        if abs(delta) > abs(r[feature_id]):
                            r[feature_id] = delta
                    else:
                        r[feature_id] = delta

            break
        else:
            overlap += 1
    return overlap, y, r


def apply_adjustment(x_orig, adjustment):
    x_new = np.array(x_orig)

    for i, d in adjustment.items():
        x_new[i] += d

    return x_new


def score_adjustments(x_orig, x_orig_path, leafs_path, dist):
    r = []

    for leaf_path in leafs_path:
        _, y, adjustment = compute_path_adjustment(x_orig, x_orig_path, leaf_path)
        x_new = apply_adjustment(x_orig, adjustment)
        cost = dist(x_new)

        r.append((cost, y, adjustment))

    r.sort(key=lambda item: item[0])        

    return r

def compute_counterfactual_of_model(model, x, y_pred, features_whitelist = [0, 1, 2, 3, 4]):
    x = x.flatten()

    # Enumerate all leafs
    leafs = get_leafs_from_tree(model.tree_, classifier=False)
    
    # Filter leafs for better predictions
    leafs = list(filter(lambda z: z[-1][2] > y_pred, leafs))

    # Sort by prediction
    #leafs.sort(key=lambda z: z[-1][2])

    # Compute path of sample
    path_of_x = list(model.decision_path([x]).indices)

    # Score and sort all counterfactuals of the sample
    regularization = lambda z: np.linalg.norm(x - z, ord=1)
    counterfactuals = score_adjustments(x, path_of_x, leafs, regularization)

    counterfactuals = [apply_adjustment(x, cf[2]) for cf in counterfactuals]

    # Choose a counterfactual -> simply take the first one (closest)  # TODO: Or choose the one with the largest or larger prediction?
    x_cf = None if len(counterfactuals) == 0 else counterfactuals[0]

    return x_cf

    """
    # initialize counterfactual variable (tmp and final) with nans for now
    x_cf_current = [np.nan,np.nan,np.nan,np.nan,np.nan]
    x_cf = [np.nan,np.nan,np.nan,np.nan,np.nan]
    y_cf = 0.0
    delta = 0.0

    # try to compute counterfactual for increasingly good y_target values
    # increment y_target value by 0.01 for each try
    # when a valid CF is found, be happy and return it
    for y_target in np.arange(y_pred + 0.05, 2.0, 0.01):
        # in case we don't achieve `y_target` exactly, be happy if we do not deviate more than 0.05 from it
        done = lambda z: np.abs(y_target - z) <= 0.05
        # generate_counterfactual
        try:
            x_cf_current, y_cf, delta = generate_counterfactual(model, x.flatten(), y_target=y_target.item(), features_whitelist=features_whitelist, C=0.001, regularization="l2", optimizer="nelder-mead", done=done, return_as_dict=False)
        # if something went wrong (most likely: CF not found exception)
        except Exception as e:
            # print exception to know what went on
            print(repr(e))
            pass
        # round the computed CF
        x_cf_round = np.round(x_cf_current)
        # set -0 entries to 0
        x_cf_round[x_cf_round == -0] = 0
        # more prints (all sanity checks)
        #print("INPUT")
        #print(x.flatten())
        #print("ROUNDED CF:")
        #print(x_cf_round)
        #if there is no NaN in the computed cf, check if it's a valid CF
        if not np.isnan(x_cf_round).any():
            # is result different from input when rounded?
            comparison = x_cf_round == x.flatten()
            if not comparison.all():
                print("CF and input different! Check!")
                # does result contain no number larger than 6
                if all(vals <= 6 for vals in x_cf_round):
                    print("CF does not conatain vals > 6! Check!")
                    # if no entry is smaller than 0
                    if all(vals >= 0 for vals in x_cf_round):
                        print("CF does not conatain vals < 0! Check!")
                        # accept solution and break
                        x_cf=x_cf_round
                        break

    # print model input, computed counterfactual, rounded version (all sanity checks)
    print("input and counterfactual")
    print(x.flatten())
    print(x_cf)
    print(np.round(x_cf))
    x_cf = np.round(x_cf)
    #print(SNnew)

    return x_cf
    """