from pymoo.model.problem import Problem
import numpy as np
from pymoo.util.nds.non_dominated_sorting import NonDominatedSorting
from sklearn.preprocessing import MinMaxScaler

from .constraints import Constraints
from .feature_encoder import FeatureEncoder
from .classifier import Classifier
from .utils import get_scaler_from_norm

NB_OBJECTIVES = 3


class DefaultProblem(Problem):
    def __init__(
        self,
        x_initial_state: np.ndarray,
        classifier: Classifier,
        minimize_class: int,
        encoder: FeatureEncoder,
        constraints: Constraints,
        scale_objectives: True,
        save_history=False,
        ml_scaler=None,
        norm=np.inf,
    ):
        # Essential passed parameters
        self.x_initial_ml = x_initial_state
        self.classifier = classifier
        self.minimize_class = minimize_class
        self._constraints = constraints
        self.encoder = encoder

        # Optional parameters
        self.scale_objectives = scale_objectives
        self._save_history = save_history
        self.norm = norm

        # Computed attributes
        self.x_initial_f_mm = encoder.normalise(x_initial_state)
        self._create_default_scaler()
        xl, xu = encoder.get_min_max_genetic()

        self._ml_scaler = ml_scaler

        self._history = []

        self.last_pareto = {
            "X": np.empty((0, self.encoder.get_genetic_v_length())),
            "F": np.empty((0, self.get_nb_objectives())),
        }
        self.nds = NonDominatedSorting()
        self.nb_eval = 0

        super().__init__(
            n_var=self.encoder.get_genetic_v_length(),
            n_obj=self.get_nb_objectives(),
            n_constr=0,
            xl=xl,
            xu=xu,
        )

    def get_initial_state(self):
        return self.x_initial_ml

    def get_history(self):
        return self._history

    def get_nb_objectives(self):
        return NB_OBJECTIVES

    def _create_default_scaler(self):
        # Objective scalers (Compute only once)
        self._f2_scaler = get_scaler_from_norm(self.norm, self.x_initial_f_mm.shape[0])

    def _obj_misclassify(self, x_ml: np.ndarray) -> np.ndarray:
        f1 = self.classifier.predict_proba(x_ml)[:, self.minimize_class]
        return f1

    def _obj_distance(self, x_f_mm: np.ndarray) -> np.ndarray:

        if self.norm in ["inf", np.inf]:
            f2 = np.linalg.norm(x_f_mm - self.x_initial_f_mm, ord=np.inf, axis=1)
        elif self.norm in ["2", 2]:
            f2 = np.linalg.norm(x_f_mm - self.x_initial_f_mm, ord=2, axis=1)
        else:
            raise NotImplementedError

        if self.scale_objectives:
            f2 = self._f2_scaler.transform(f2.reshape(-1, 1))[:, 0]
        return f2

    def _calculate_constraints(self, x_f):
        G = self._constraints.evaluate(x_f)
        G = G * (G > 0).astype(np.float)

        return G

    def _evaluate(self, x, out, *args, **kwargs):

        # Sanity check
        if (x - self.xl < 0).sum() > 0:
            print("Lower than lower bound.")

        if (x - self.xu > 0).sum() > 0:
            print("Lower than lower bound.")

        # --- Prepare necessary representation of the samples

        # Genetic representation is in x

        # Machine learning representation
        x_f = self.encoder.genetic_to_ml(x, self.x_initial_ml)

        # Min max scaled representation
        x_f_mm = self.encoder.normalise(x_f)

        # ML scaled
        x_ml = x_f
        if self._ml_scaler is not None:
            x_ml = self._ml_scaler.transform(x_f)

        # --- Objectives
        f1 = self._obj_misclassify(x_ml)
        f2 = self._obj_distance(x_f_mm)

        # --- Domain constraints
        G_all = self._calculate_constraints(x_f)
        G = G_all.sum(axis=1)

        F = [f1, f2, G] + self._evaluate_additional_objectives(x, x_f, x_f_mm, x_ml)

        # --- Output
        out["F"] = np.column_stack(F)

        # Save output
        if "reduced" in self._save_history:
            self._history.append(out["F"])
        elif "full" in self._save_history:
            self._history.append(np.concatenate((out["F"], G_all), axis=1))

    def _evaluate_additional_objectives(self, x, x_f, x_f_mm, x_ml):
        return []
