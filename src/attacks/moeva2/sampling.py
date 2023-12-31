import numpy as np
from art.utils import projection
from pymoo.model.sampling import Sampling
from pymoo.util.normalization import denormalize, normalize
from src.utils import sample_in_norm


class MixedSamplingLp(Sampling):
    """
    Randomly sample points in the real space by considering the lower and upper bounds of the problem.
    """

    def __init__(
        self, var_type=float, ratio_perturbed=0.5, eps=0.1, norm=2, type_mask=None
    ) -> None:
        super().__init__()
        self.var_type = var_type
        self.eps = eps
        self.norm = norm
        self.type_mask = type_mask
        self.ratio_perturbed = ratio_perturbed

    def _do(self, problem, n_samples, **kwargs):

        # Retrieve original
        x_initial_f = problem.x_initial_ml

        # Retrieve the genetic part and normalise it
        x_initial_gen = problem.encoder.ml_to_genetic(x_initial_f.reshape(1, -1))[0]
        x_initial_gen_normalised = normalize(x_initial_gen, problem.xl, problem.xu)

        # Create n_var*ratio of new samples
        nb_perturbed_sample = int(np.rint(self.ratio_perturbed * n_samples))
        nb_not_perturbed_sample = n_samples - nb_perturbed_sample

        x_perturbation = sample_in_norm(
            nb_perturbed_sample, problem.n_var, self.eps, self.norm
        )
        x_perturbed = x_initial_gen_normalised + x_perturbation
        x_perturbed = np.clip(x_perturbed, 0, 1)

        x_perturbed = denormalize(x_perturbed, problem.xl, problem.xu)

        # Apply int
        mask_int = self.type_mask != "real"
        x_perturbed[:, mask_int] = np.rint(x_perturbed[:, mask_int])

        out = np.concatenate(
            (np.tile(x_initial_gen, (nb_not_perturbed_sample, 1)), x_perturbed)
        )

        return out


class InitialStateSampling(Sampling):
    """
    Randomly sample points in the real space by considering the lower and upper bounds of the problem.
    """

    def __init__(self, type_mask) -> None:
        self.type_mask = type_mask
        super().__init__()

    def _do(self, problem, n_samples, **kwargs):

        # Retrieve original
        x_initial_f = problem.x_initial_ml

        # Encode to genetic
        x_initial_gen = problem.encoder.ml_to_genetic(x_initial_f.reshape(1, -1))[0]

        x_generated = np.tile(x_initial_gen, (n_samples, 1))

        mask_int = self.type_mask != "real"

        x_generated[:, mask_int] = np.rint(x_generated[:, mask_int]).astype(int)

        return x_generated
