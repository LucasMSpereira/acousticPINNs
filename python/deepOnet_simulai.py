import os
from argparse import ArgumentParser

import matplotlib.pyplot as plt
import numpy as np

# In order to execute this script, it is necessary to
# set the environment variable engine as "pytorch" before initializing
# simulai
os.environ["engine"] = "pytorch"

from simulai.file import SPFile
from simulai.optimization import Optimizer
from simulai.residuals import SymbolicOperator

# Reading command line arguments.
parser = ArgumentParser(description="Reading input parameters")

parser.add_argument("--save_path", type=str, help="Save path", default="/tmp")
args = parser.parse_args()

save_path = args.save_path

Q = 1_000
N = int(5e4)

rho = 28
bheta = 8 / 3
sigma = 10

initial_state_test = np.array([1, 0, 0])

t_intv = [0, 1]
s_intv = np.stack([[-50, -50, -50], [50, 50, 50]], axis=0)

# The expression we aim at minimizing
f_x = "D(x, t) - sigma*(y - x)"
f_y = "D(y, t) - x*(rho - z) + y"
f_z = "D(z, t) - x*y + bheta*z"

U_t = np.random.uniform(low=t_intv[0], high=t_intv[1], size=Q)
U_s = np.random.uniform(low=s_intv[0], high=s_intv[1], size=(N, 3))

branch_input_train = np.tile(U_s[:, None, :], (1, Q, 1)).reshape(N * Q, -1)
trunk_input_train = np.tile(U_t[:, None], (N, 1))

branch_input_test = np.tile(initial_state_test[None, :], (Q, 1))
trunk_input_test = np.sort(U_t[:, None], axis=0)

initial_states = U_s

input_labels = ["t"]
output_labels = ["x", "y", "z"]

n_inputs = len(input_labels)
n_outputs = len(output_labels)

lambda_1 = 0.0  # Penalty for the L¹ regularization (Lasso)
lambda_2 = 0.0  # Penalty factor for the L² regularization
n_epochs = 400_000  # Maximum number of iterations for ADAM
lr = 1e-3  # Initial learning rate for the ADAM algorithm


def model():
    from simulai.models import ImprovedDeepONet
    from simulai.regression import SLFNN, ConvexDenseNetwork

    n_latent = 100
    n_inputs_b = 3
    n_inputs_t = 1
    n_outputs = 3

    # Configuration for the fully-connected trunk network
    trunk_config = {
        "layers_units": 6 * [100],  # Hidden layers
        "activations": "tanh",
        "input_size": n_inputs_t,
        "output_size": n_latent * n_outputs,
        "name": "trunk_net",
    }

    # Configuration for the fully-connected branch network
    branch_config = {
        "layers_units": 6 * [100],  # Hidden layers
        "activations": "tanh",
        "input_size": n_inputs_b,
        "output_size": n_latent * n_outputs,
        "name": "branch_net",
    }

    # Instantiating and training the surrogate model
    trunk_net = ConvexDenseNetwork(**trunk_config)
    branch_net = ConvexDenseNetwork(**branch_config)

    encoder_trunk = SLFNN(input_size=n_inputs_t, output_size=100, activation="tanh")
    encoder_branch = SLFNN(input_size=n_inputs_b, output_size=100, activation="tanh")

    # It prints a summary of the network features
    trunk_net.summary()
    branch_net.summary()

    lorenz_net = ImprovedDeepONet(
        trunk_network=trunk_net,
        branch_network=branch_net,
        encoder_trunk=encoder_trunk,
        encoder_branch=encoder_branch,
        var_dim=n_outputs,
        devices="gpu",
        model_id="lorenz_net",
    )

    return lorenz_net


lorenz_net = model()

residual = SymbolicOperator(
    expressions=[f_x, f_y, f_z],
    input_vars=input_labels,
    output_vars=output_labels,
    function=lorenz_net,
    inputs_key="input_trunk",
    constants={"sigma": sigma, "rho": rho, "bheta": bheta},
    device="gpu",
    engine="torch",
)

# Maximum derivative magnitudes to be used as loss weights
penalties = [1, 1, 1]
batch_size = 10_000

optimizer_config = {"lr": lr}

input_data = {"input_branch": branch_input_train, "input_trunk": trunk_input_train}

optimizer = Optimizer(
    "adam",
    params=optimizer_config,
    lr_decay_scheduler_params={
        "name": "ExponentialLR",
        "gamma": 0.9,
        "decay_frequency": 5_000,
    },
)

params = {
    "lambda_1": lambda_1,
    "lambda_2": lambda_2,
    "residual": residual,
    "initial_input": {"input_trunk": np.zeros((N, 1)), "input_branch": initial_states},
    "initial_state": initial_states,
    "weights_residual": [1, 1, 1],
    "weights": penalties,
}

optimizer.fit(
    op=lorenz_net,
    input_data=input_data,
    n_epochs=n_epochs,
    loss="opirmse",
    params=params,
    device="gpu",
    batch_size=batch_size,
)

# Saving model
print("Saving model.")
saver = SPFile(compact=False)
saver.write(
    save_dir=save_path, name="lorenz_deeponet", model=lorenz_net, template=model
)

approximated_data = lorenz_net.eval(
    trunk_data=trunk_input_test, branch_data=branch_input_test
)

for ii in range(n_outputs):
    plt.plot(approximated_data[:, ii], label="Approximated")
    plt.legend()
    plt.savefig(f"lorenz_deeponet_time_int_{ii}.png")
    plt.show()