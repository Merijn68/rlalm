# Lets try with vectorized environments
import gymnasium as gym
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import DummyVecEnv, SubprocVecEnv
from stable_baselines3.common.env_util import make_vec_env
from stable_baselines3.common.utils import set_random_seed
from datetime import datetime
from pathlib import Path
import sys


ROOT_DIR = Path(__file__).parents[2].absolute()
sys.path.append(str(ROOT_DIR))

from src.data.definitions import MODEL_PATH


def make_env(env_id: str, rank: int, seed: int = 0, env_kwargs: dict = {}):
    """
    Utility function for multiprocessed env.

    :param env_id: the environment ID
    :param num_env: the number of environments you wish to have in subprocesses
    :param seed: the inital seed for RNG
    :param rank: index of the subprocess
    """

    def _init():
        env = gym.make(env_id, start=1, render_mode="human")
        env.reset(seed=seed + rank)
        return env

    set_random_seed(seed)
    return _init


def linear_schedule(initial_value: float):
    """
    Linear learning rate schedule.

    :param initial_value: Initial learning rate.
    :return: schedule that computes
      current learning rate depending on remaining progress
    """

    def func(progress_remaining: float) -> float:
        """
        Progress will decrease from 1 (beginning) to 0.

        :param progress_remaining:
        :return: current learning rate
        """
        return progress_remaining * initial_value

    return func


def main():
    env_id = "gym_basic:shower-v1"
    num_cpu = 2  # Number of processes to use
    # Create the vectorized environment

    vec_env = SubprocVecEnv(
        [make_env(env_id, rank=i, env_kwargs={"start": 1}) for i in range(num_cpu)]
    )

    # Stable Baselines provides you with make_vec_env() helper
    # which does exactly the previous steps for you.
    # You can choose between `DummyVecEnv` (usually faster) and `SubprocVecEnv`
    # env = make_vec_env(env_id, n_envs=num_cpu, seed=0, vec_env_cls=SubprocVecEnv)

    tensorboard_logs = "./tensorboard_logs/"

    model = PPO(
        "MlpPolicy",
        vec_env,
        tensorboard_log=tensorboard_logs,
        verbose=1,
        learning_rate=linear_schedule(0.001),
    )
    model.learn(total_timesteps=100, progress_bar=True)  # 3e5
    modelpath = Path(
        MODEL_PATH,
        "PPO_V" + "_" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".zip",
    )
    model.save(modelpath)
    del model  # remove to demonstrate saving and loading

    env = gym.make("gym_basic:shower-v1", render_mode="human")
    model = PPO.load(path=modelpath, env=env)
    env.set_render_output(modelpath.stem)

    obs, info = env.reset()
    score = 0
    terminated = False
    truncated = False
    while not terminated and not truncated:
        action, _state = model.predict(obs)
        obs, reward, terminated, truncated, info = env.step(action)
        score = score + reward
        env.render()
    env.close()

    print("all done... That's all folks! ")


if __name__ == "__main__":
    main()
