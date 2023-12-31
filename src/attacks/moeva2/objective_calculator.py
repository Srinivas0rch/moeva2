import sys
from typing import List

import numpy
import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from pymoo.model.problem import Problem
from tqdm import tqdm

from .classifier import Classifier
from .constraints import Constraints
from .feature_encoder import get_encoder_from_constraints
from .result_process import EfficientResult
from .utils import get_one_hot_encoding_constraints

numpy.set_printoptions(threshold=sys.maxsize)


class ObjectiveCalculator:
    def __init__(
        self,
        classifier: Classifier,
        constraints: Constraints,
        minimize_class: int,
        thresholds: dict,
        min_max_scaler,
        norm=np.inf,
        ml_scaler=None,
        problem_class=None,
        n_jobs=1
    ):
        self._classifier = classifier
        self._constraints = constraints
        self._thresholds = thresholds
        self._ml_scaler = ml_scaler
        self._problem_class = problem_class
        self._minimize_class = minimize_class
        self._encoder = get_encoder_from_constraints(self._constraints)
        self._min_max_scaler = min_max_scaler
        self.norm = norm
        self.n_jobs = n_jobs

    def _calculate_objective(self, x_initial, x_f):

        # Constraints
        constraint_violation = Problem.calc_constraint_violation(
            np.concatenate(
                (
                    self._constraints.evaluate(x_f),
                    get_one_hot_encoding_constraints(
                        self._constraints.get_feature_type(), x_f
                    ).reshape(-1, 1),
                ),
                axis=1,
            )
        ).reshape(-1)

        # Misclassify

        x_ml = x_f
        if self._ml_scaler is not None:
            x_ml = self._ml_scaler.transform(x_f)
        f1 = self._classifier.predict_proba(x_ml)[:, self._minimize_class]

        # Distance

        # Scale and check scaling

        x_i_scaled = self._min_max_scaler.transform(x_initial.reshape(1, -1))
        x_scaled = self._min_max_scaler.transform(x_f)
        tol = 0.0001
        assert np.all(x_i_scaled >= 0 - tol)
        assert np.all(x_i_scaled <= 1 + tol)
        assert np.all(x_scaled >= 0 - tol)
        assert np.all(x_scaled <= 1 + tol)

        f2 = np.linalg.norm(
            x_i_scaled - x_scaled,
            ord=self.norm,
            axis=1,
        )

        return np.column_stack([constraint_violation, f1, f2])

    def _objective_respected(self, objective_values):
        constraints_respected = objective_values[:, 0] <= 0
        misclassified = objective_values[:, 1] < self._thresholds["f1"]
        l2_in_ball = objective_values[:, 2] <= self._thresholds["f2"]
        return np.column_stack(
            [
                constraints_respected,
                misclassified,
                l2_in_ball,
                constraints_respected * misclassified,
                constraints_respected * l2_in_ball,
                misclassified * l2_in_ball,
                constraints_respected * misclassified * l2_in_ball,
            ]
        )

    def _objective_array(self, x_initial, x_f):
        objective_values = self._calculate_objective(x_initial, x_f)
        return self._objective_respected(objective_values)

    def success_rate(self, x_initial, x_f):
        return self._objective_array(x_initial, x_f).mean(axis=0)

    def at_least_one(self, x_initial, x_f):
        return np.array(self.success_rate(x_initial, x_f) > 0)

    def success_rate_3d(self, x_initial, x):
        at_least_one = np.array(
            [
                self.success_rate(x_initial[i], e) > 0
                for i, e in tqdm(enumerate(x), total=len(x))
            ]
        )
        return at_least_one.mean(axis=0)

    def success_rate_3d_df(self, x_initial, x):
        success_rates = self.success_rate_3d(x_initial, x)

        columns = ["o{}".format(i + 1) for i in range(success_rates.shape[0])]
        success_rate_df = pd.DataFrame(
            success_rates.reshape([1, -1]),
            columns=columns,
        )
        return success_rate_df

    def success_rate_genetic(self, results: List[EfficientResult]):

        initial_states = [result.initial_state for result in results]
        # Use last pop or all gen pareto front to compute objectives.
        # pops_x = [result.X.astype(np.float64) for result in results]
        # pops_x = [result.pareto.astype(np.float64) for result in results]
        pops_x = [
            np.array([ind.X.astype(np.float64) for ind in result.pop])
            for result in results
        ]
        # Convert to ML representation
        pops_x_f = [
            self._encoder.genetic_to_ml(pops_x[i], initial_states[i])
            for i in range(len(results))
        ]

        return self.success_rate_3d(initial_states, pops_x_f)

    def get_success(self, x_initial, x_f):
        raise NotImplementedError

    def _get_one_successful(
        self,
        x_initial,
        x_generated,
        preferred_metrics="misclassification",
        order="asc",
        max_inputs=-1,
    ):

        metrics_to_index = {"misclassification": 1, "distance": 2}

        # Calculate objective and respected values
        objective_values = self._calculate_objective(x_initial, x_generated)
        objective_respected = self._objective_respected(objective_values)

        # Sort by the preferred_metrics parameter
        sorted_index = np.argsort(
            objective_values[:, metrics_to_index[preferred_metrics]]
        )

        # Reverse order if parameter set
        if order == "desc":
            sorted_index = sorted_index[::-1]

        # Cross the sorting with the successful attacks
        sorted_index_success = sorted_index[objective_respected[:, -1]]

        # Bound the number of input to return
        if max_inputs > -1:
            sorted_index_success = sorted_index_success[:1]

        success_full_attacks = x_generated[sorted_index_success]

        return success_full_attacks

    def get_successful_attacks(
        self,
        x_initials,
        x_generated,
        preferred_metrics="misclassification",
        order="asc",
        max_inputs=-1,
        return_index_success=False
    ):

        successful_attacks = []

        if self.n_jobs == 1:
            for i, x_initial in tqdm(enumerate(x_initials), total=len(x_initials)):
                successful_attacks.append(
                    self._get_one_successful(
                        x_initial, x_generated[i], preferred_metrics, order, max_inputs
                    )
                )

        # Parallel run
        else:
            processed_results = Parallel(n_jobs=self.n_jobs, prefer="threads")(
                delayed(self._get_one_successful)(x_initial, x_generated[i], preferred_metrics, order, max_inputs)
                for i, x_initial in tqdm(enumerate(x_initials), total=len(x_initials))
            )
            for processed_result in processed_results:
                successful_attacks.append(processed_result)

        if return_index_success:
            index_success = np.array([len(e) >= 1 for e in successful_attacks])
        successful_attacks = np.concatenate(successful_attacks, axis=0)

        if return_index_success:
            return successful_attacks, index_success
        else:
            return successful_attacks

    def get_successful_attacks_results(
        self,
        results: List[EfficientResult],
        preferred_metrics="misclassification",
        order="asc",
        max_inputs=-1,
    ):

        initial_states = [result.initial_state for result in results]
        pops_x = [
            np.array([ind.X.astype(np.float64) for ind in result.pop])
            for result in results
        ]
        pops_x_f = [
            self._encoder.genetic_to_ml(pops_x[i], initial_states[i])
            for i in range(len(results))
        ]

        successful_attacks = self.get_successful_attacks(
            initial_states,
            pops_x_f,
            preferred_metrics,
            order,
            max_inputs,
        )

        return successful_attacks
