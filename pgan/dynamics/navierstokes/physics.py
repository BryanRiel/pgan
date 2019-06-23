#-*- coding: utf-8 -*-

import numpy as np
import tensorflow as tf
from pgan.networks.common import DenseNet, Model
from tqdm import tqdm
import logging

class PINN(Model):
    """
    Model for generating solutions to a PDE.
    """

    def __init__(self, solution_layers, physical_model, name='PINN'):
        """
        Store metadata about network architectures and domain bounds.
        """
        # Initialize parent class
        super().__init__(name=name)

        # Create solution network
        self.solution_net = SolutionNet(solution_layers, name='solution')

        # Cache pre-trained and pre-configured physics model
        self.physics = physical_model

        # Create dictionary of models
        self.submodels = {'solution': self.solution_net}

        return

    def build(self, learning_rate=0.001, graph=None, inter_op_cores=1, intra_op_threads=1):
        """
        Construct all computation graphs, placeholders, loss functions, and optimizers.
        """
        # Placeholders for boundary points
        self.Xb = tf.placeholder(tf.float32, shape=[None, 1])
        self.Yb = tf.placeholder(tf.float32, shape=[None, 1])
        self.Tb = tf.placeholder(tf.float32, shape=[None, 1])
        self.Wb = tf.placeholder(tf.float32, shape=[None, 1])

        # Placeholder for collocation points
        self.Xcoll = tf.placeholder(tf.float32, shape=[None, 1])
        self.Ycoll = tf.placeholder(tf.float32, shape=[None, 1])
        self.Ucoll = tf.placeholder(tf.float32, shape=[None, 1])
        self.Vcoll = tf.placeholder(tf.float32, shape=[None, 1])
        self.Tcoll = tf.placeholder(tf.float32, shape=[None, 1])

        # Compute graph for boundary and initial data
        self.Wb_pred = self.solution_net(self.Xb, self.Yb, self.Tb)

        # Compute graph for collocation points (physics consistency)
        self.Wcoll = self.solution_net(self.Xcoll, self.Ycoll, self.Tcoll)
        F_pred = self.physics(self.Wcoll, self.Xcoll, self.Ycoll, self.Ucoll,
                              self.Vcoll, self.Tcoll)

        # Scalar value for all loss functions to improve precision
        self.scale = 1000.0

        # Loss functions
        self.b_loss = self.scale * tf.reduce_mean(tf.square(self.Wb_pred - self.Wb))
        self.f_loss = self.scale * tf.reduce_mean(tf.square(F_pred))
        self.loss = self.b_loss + self.f_loss

        # Optimization steps
        self.optimizer = tf.train.AdamOptimizer(learning_rate=learning_rate)
        self.train_op = self.optimizer.minimize(
            self.loss, var_list=self.solution_net.trainable_variables
        )

        # Finalize building via the super class
        super().build(graph=graph,
                      inter_op_cores=inter_op_cores,
                      intra_op_threads=intra_op_threads)

        return

    def train(self, train, test=None, batch_size=128, n_epochs=1000, verbose=True):
        """
        Run training over batches of collocation points.
        """
        # Compute the number of batches for collocation points
        n_train = train.tcoll.shape[0]
        n_batches = int(np.ceil(n_train / batch_size))

        # Compute batch size for boundary points
        n_boundary = train.x.shape[0]
        boundary_batch = int(np.ceil(n_boundary / n_batches))
        n_batches_boundary = int(np.ceil(n_boundary / boundary_batch))

        print('Collocation: using %d batches of size %d' % (n_batches, batch_size))
        print('Boundary: using %d batches of size %d' % (n_batches_boundary, boundary_batch))

        # Training iterations
        for epoch in tqdm(range(n_epochs)):

            # Get random indices to shuffle training examples
            ind = np.random.permutation(n_boundary)
            Xb = train.x[ind]
            Yb = train.y[ind]
            Tb = train.t[ind]
            Wb = train.w[ind]

            ind = np.random.permutation(n_train)
            Xcoll = train.xcoll[ind]
            Ycoll = train.ycoll[ind]
            Ucoll = train.ucoll[ind]
            Vcoll = train.vcoll[ind]
            Tcoll = train.tcoll[ind]

            # Loop over minibatches
            losses = np.zeros((n_batches, 2))
            start = 0
            start_boundary = 0
            for b in range(n_batches):

                # Construct slices
                slice_boundary = slice(start_boundary, start_boundary + boundary_batch)
                slice_coll = slice(start, start + batch_size)

                # Create feed dictionary for training points
                feed_dict = {
                    self.Xb: Xb[slice_boundary],
                    self.Yb: Yb[slice_boundary],
                    self.Tb: Tb[slice_boundary],
                    self.Wb: Wb[slice_boundary],
                    self.Xcoll: Xcoll[slice_coll],
                    self.Ycoll: Ycoll[slice_coll],
                    self.Ucoll: Ucoll[slice_coll],
                    self.Vcoll: Vcoll[slice_coll],
                    self.Tcoll: Tcoll[slice_coll]
                }

                # Run training operation for generator and compute losses
                values = self.sess.run(
                    [self.train_op, self.b_loss, self.f_loss],
                    feed_dict=feed_dict
                )
                losses[b,:] = values[1:]

                # Update starting batch indices
                start += batch_size
                start_boundary += boundary_batch

            # Average losses over all minibatches
            b_loss, f_loss = np.mean(losses, axis=0)

            # Compute testing losses
            if test is not None:
                feed_dict = {
                    self.Xb: test.x,
                    self.Yb: test.y,
                    self.Tb: test.t,
                    self.Wb: test.w,
                    self.Xcoll: test.xcoll,
                    self.Ycoll: test.ycoll,
                    self.Ucoll: test.ucoll,
                    self.Vcoll: test.vcoll,
                    self.Tcoll: test.tcoll
                }
                b_loss_test, f_loss_test = self.sess.run(
                    [self.b_loss, self.f_loss],
                    feed_dict=feed_dict
                )

            # Log training performance
            if verbose:
                if test is not None:
                    logging.info('%d %f %f %f %f' % (epoch, b_loss, f_loss,
                                                     b_loss_test, f_loss_test))
                else:
                    logging.info('%d %f %f' % (epoch, b_loss, f_loss))

        return

    def predict(self, X, Y, T):
        """
        Generate predictions from PINN.
        """
        # Feed dictionary will be the same for all samples
        feed_dict = {self.Xcoll: X.reshape(-1, 1),
                     self.Ycoll: Y.reshape(-1, 1),
                     self.Tcoll: T.reshape(-1, 1)}

        # Run graph for solution for collocation points
        W = self.sess.run(self.Wcoll, feed_dict=feed_dict)

        return W


class DeepHPM(Model):
    """
    Model for learning hidden dynamics from data.
    """

    def __init__(self, solution_layers, pde_layers, name='deepHPM'):
        """
        Store metadata about network architectures and domain bounds.
        """
        # Initialize parent class
        super().__init__(name=name)

        # Create PDE (physics consistency) network
        self.pde_net = PDENet(pde_layers, name='pde')

        # Create solution network
        self.solution_net = SolutionNet(solution_layers, name='solution')

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


# end of file
