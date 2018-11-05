import tensorflow as tf
import numpy as np
from config import Config
from agent import Agent
from Environment.environment import Environment


class Reinforce:
    def __init__(self):
        #   define the input variables
        self.agent = Agent()
        self.env = Environment()
        self.Y = tf.placeholder(tf.int32, (None,), "action")
        self.R = tf.placeholder(tf.float32, (None,), "reward")
        self.DR = tf.placeholder(tf.float32, (None,), "discounted_reward")

        #   for log
        self.LR = tf.placeholder(tf.float32, (None,), "last_reward")
        self.HR = tf.placeholder(tf.float32, (None,), "hit_rate")

        #   define losses
#        self.policy_gradient_loss = tf.reduce_mean((self.DR - self.agent.value)
        self.policy_gradient_loss = tf.reduce_mean((self.DR)
                                                   * tf.nn.sparse_softmax_cross_entropy_with_logits(
            logits=self.agent.logits, labels=self.Y))
        self.value_loss = Config.value_scale * tf.reduce_mean(tf.square(self.DR - self.agent.value))
#        self.loss = self.policy_gradient_loss + self.value_loss
        self.loss = self.policy_gradient_loss

        #   create optimizer
        self.optimizer = tf.train.AdamOptimizer(Config.lr)
        self.grads = tf.gradients(self.loss, tf.trainable_variables())
        self.grads, _ = tf.clip_by_global_norm(self.grads, Config.gradient_clip)
        self.grads_and_vars = list(zip(self.grads, tf.trainable_variables()))
        self.train_op = self.optimizer.apply_gradients(self.grads_and_vars)

        #   initialize Session
        self.sess = tf.Session()
        init = tf.global_variables_initializer()
        self.sess.run(init)

        #   setup tensorboard writer
        self.writer = tf.summary.FileWriter(Config.summaries_dir)
        tf.summary.scalar("mean last reward", tf.reduce_mean(self.LR))
        tf.summary.scalar("total loss", self.loss)
        tf.summary.scalar("policy gradient loss", self.policy_gradient_loss)
        tf.summary.scalar("value loss", self.value_loss)
        tf.summary.scalar("hit rate", tf.reduce_mean(self.HR))
        self.write_op = tf.summary.merge_all()

        self.saver = tf.train.Saver(tf.global_variables())

    @staticmethod
    def discount(gamma, rewards):
        discounted_rewards = np.zeros_like(rewards)
        G = 0.0
        for i in reversed(range(0, len(rewards))):
            G = gamma * G + rewards[i]
            discounted_rewards[i] = G
        return discounted_rewards

    def next_batch(self, batch_size, render):
        states, actions, rewards, discounted_rewards, last_rewards, hits = [], [], [], [], [], []
        num_episodes = 0
        while len(states) < batch_size:
            rewards = []
            state = np.zeros(Config.num_fields)
            while np.sum(state) < Config.target_combination_len:
                action = self.sess.run(self.agent.action, feed_dict={self.agent.X: state.reshape((1, -1))})
                action = action[0][0]

                state2, reward = self.env.get_reward(state, action)

                states.append(state)
                actions.append(action)
                rewards.append(reward)

                state = state2
            num_episodes += 1
            discounted_rewards.append(self.discount(Config.gamma, rewards))
            last_rewards.append(rewards[-1])
            hits.append(self.env.check_hit(state))
        return np.stack(states), np.stack(actions), np.concatenate(discounted_rewards), np.array(last_rewards), np.array(hits), num_episodes

    def load(self, model_dir):
        print("Load Model...")
        self.saver.restore(self.sess, tf.train.latest_checkpoint(model_dir))

    def save(self, model_dir, step):
        print("Saved Model...")
        self.saver.save(self.sess, Config.model_dir + "/model", global_step=step)

    def train(self, num_steps=1000):
        tot_mean_last_rewards = []

        for step in range(num_steps):
            # gather training data
            states, actions, discounted_rewards, last_rewards, hits, num_episodes = \
                self.next_batch(Config.reinforce_batch_size, False)

            hit_rate = np.mean(hits.astype(np.float32))
            mean_last_rewards = np.mean(last_rewards)
            tot_mean_last_rewards.append(mean_last_rewards)

            if step % Config.epoch_display_periods == 0:
                print('Epoch {} {:2.1f}'.format(step, (step + 1.0) / num_steps))
                print('Trained episodes: {}  Mean Last Reward: {:4.2f}  Total Average: {:4.2f} Hit rate: {:4.2f}'.format(num_episodes, mean_last_rewards, np.mean(tot_mean_last_rewards), hit_rate))

            # update network
            self.sess.run(self.train_op, feed_dict={self.agent.X: states, self.Y: actions, self.DR: discounted_rewards, self.LR:last_rewards})

            # write summaries
            summary = self.sess.run(self.write_op,
                    feed_dict={self.agent.X: states, self.Y: actions, self.DR: discounted_rewards, self.LR:last_rewards, self.HR:hits})
            self.writer.add_summary(summary, step)
            self.writer.flush()

            if (step + 1) % Config.save_periods == 0:
                self.save(Config.model_dir, step)
