#-*- coding: utf-8 -*-

import numpy as np
import tensorflow as tf
from pgan.networks.common import DenseNet, Model
from tqdm import tqdm
import logging

class DeepHPM(Model):
    """
    Model for learning hidden dynamics from data.
    """

    def __init__(self, solution_layers, pde_layers, lower_bound, upper_bound, name='deepHPM'):
        """
        Store metadata about network architectures and domain bounds.
        """
        # Initialize parent class
        super().__init__(name=name)

        # Create PDE (physics consistency) network
        self.pde_net = PDENet(pde_layers, name='pde')

        # Create solution network
        self.solution_net = SolutionNet(
            solution_layers, np.array(upper_bound), np.array(lower_bound), name='solution'
        )

        # Create dictionary of models
        self.submodels = {'pde': self.pde_net, 'solution': self.solution_net}

        return

    def build(self, learning_rate=0.001, graph=None, inter_op_cores=1, intra_op_threads=1):
        """
        Construct all computation graphs, placeholders, loss functions, and optimizers.
        """
        # Placeholders for data
        self.T = tf.placeholder(tf.float32, shape=[None, 1])
        self.X = tf.placeholder(tf.float32, shape=[None, 1])
        self.Y = tf.placeholder(tf.float32, shape=[None, 1])
        self.U = tf.placeholder(tf.float32, shape=[None, 1])
        self.V = tf.placeholder(tf.float32, shape=[None, 1])
        self.W = tf.placeholder(tf.float32, shape=[None, 1])

        # Compute graph for solution network
        self.W_pred = self.solution_net(self.X, self.Y, self.T)

        # Compute graph for residual network
        self.F_pred = self.pde_net(self.W_pred, self.X, self.Y, self.U, self.V, self.T)

        # Loss function
        self.solution_loss = 1000.0 * tf.reduce_mean(tf.square(self.W_pred - self.W))
        self.pde_loss = 1000.0 * tf.reduce_mean(tf.square(self.F_pred))
        self.loss = self.solution_loss + self.pde_loss

        # Optimization step
        self.optimizer = tf.train.AdamOptimizer(learning_rate=learning_rate)
        self.train_op = self.optimizer.minimize(self.loss)

        # Finalize building via the super class
        super().build(graph=graph,
                      inter_op_cores=inter_op_cores,
                      intra_op_threads=intra_op_threads)

        return

    def train(self, train, test=None, batch_size=128, n_epochs=1000, verbose=True):
        """
        Run training.
        """
        # Compute the number of batches
        n_train = train.tcoll.shape[0]
        n_batches = int(np.ceil(n_train / batch_size))

        # Training iterations
        for epoch in tqdm(range(n_epochs)):

            # Shuffle data
            ind = np.random.permutation(n_train)
            X, Y, U, V, W, T = [getattr(train, attr)[ind] for attr in
                                ('xcoll', 'ycoll', 'ucoll', 'vcoll', 'wcoll', 'tcoll')]

            # Loop over minibatches for training
            losses = np.zeros((n_batches, 2))
            start = 0
            for b in range(n_batches):

                # Construct feed dictionary
                feed_dict = {self.T: T[start:start+batch_size],
                             self.X: X[start:start+batch_size],
                             self.Y: Y[start:start+batch_size],
                             self.U: U[start:start+batch_size],
                             self.V: V[start:start+batch_size],
                             self.W: W[start:start+batch_size]}

                # Run training operation
                _, uloss, floss = self.sess.run(
                    [self.train_op, self.solution_loss, self.pde_loss],
                    feed_dict=feed_dict
                )
                losses[b,:] = [uloss, floss]

                # Update starting batch index
                start += batch_size

            # Compute testing losses
            if test is not None:
                feed_dict = {self.X: test.xcoll, self.Y: test.ycoll, self.T: test.tcoll,
                             self.U: test.ucoll, self.V: test.vcoll, self.W: test.wcoll}
                uloss_test, floss_test = self.sess.run(
                    [self.solution_loss, self.pde_loss],
                    feed_dict=feed_dict
                )

            # Log training performance
            if verbose:
                u_loss, f_loss = np.mean(losses, axis=0)
                msg = '%06d %f %f' % (epoch, u_loss, f_loss)
                if test is not None:
                    msg += ' %f %f' % (uloss_test, floss_test)
                logging.info(msg)

        return


class PDENet(tf.keras.Model):
    """
    Feedforward network that takes in a solution tensor, computes gradients, and
    passes them through a neural network.
    """

    def __init__(self, layer_sizes, name='pde'):
        """
        Initialize and create layers.
        """
        # Initialize parent class
        super().__init__(name=name)

        # Create dense network
        self.dense = DenseNet(layer_sizes)

        return

    def call(self, w, x, y, u, v, t, training=False):
        """
        Compute gradients on inputs and generate an output.
        """
        # Compute gradients of vorticity
        w_t = tf.gradients(w, t)[0]
        w_x = tf.gradients(w, x)[0]
        w_y = tf.gradients(w, y)[0]
        w_xx = tf.gradients(w_x, x)[0]
        w_xy = tf.gradients(w_x, y)[0]
        w_yy = tf.gradients(w_y, y)[0]

        # Send to dense net
        inputs = tf.concat(values=[u, v, w, w_x, w_y, w_xx, w_xy, w_yy], axis=1)
        pde = self.dense(inputs, training=training, activate_outputs=False)

        # Residual output
        f = w_t - pde
        return f


class SolutionNet(tf.keras.Model):
    """
    Feedforward network that takes in time and space variables.
    """

    def __init__(self, layer_sizes, upper_bound, lower_bound, name='solution'):
        """
        Initialize and create layers.
        """
        # Initialize parent class
        super().__init__(name=name)

        # Save domain bounds
        self.upper_bound = upper_bound
        self.lower_bound = lower_bound

        # Create dense network
        self.dense = DenseNet(layer_sizes)

        return

    def call(self, x, y, t, training=False):
        """
        Pass inputs through network and generate an output.
        """
        # Concatenate the spatial and temporal input variables
        X = tf.concat(values=[x, y, t], axis=1)

        # Normalize by the domain boundaries
        Xn = 2.0 * (X - self.lower_bound) / (self.upper_bound - self.lower_bound) - 1.0

        # Compute dense network output
        w = self.dense(Xn, training=training, activate_outputs=False)
        return w


# end of file