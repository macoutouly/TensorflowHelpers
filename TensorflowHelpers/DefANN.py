import copy
import pdb

import numpy as np
import tensorflow as tf


class DenseLayer:
    def __init__(self, input, size, relu=False, bias=True, guided_dropconnect_mask=None, weight_normalization=False,
                 keep_prob=None, reload=True):
        """
        for weight normalization see https://arxiv.org/abs/1602.07868
        for counting the flops of operations see https://mediatum.ub.tum.de/doc/625604/625604
        :param input: input of the layer 
        :param size: layer size (number of outputs units)
        :param relu: do you use relu ?
        :param bias: do you add bias ?
        :param guided_dropconnect_mask: tensor of the mask matrix  #TODO 
        :param weight_normalization: do you use weight normalization (see https://arxiv.org/abs/1602.07868)
        :param keep_prob: a scalar tensor for dropout layer (None if you don't want to use it)
        :param reload: do you want to initialize with reloaded values
        """

        nin_ = int(input.get_shape()[1])
        self.nbparams = 0  # number of trainable parameters
        self.flops = 0  # flops for a batch on 1 data
        self.input = input
        self.weightnormed = False
        self.bias = False
        self.w = tf.get_variable(name="weights_matrix",
                            shape=[nin_, size],
                            # initializer=tf.contrib.layers.xavier_initializer(dtype=tf.float32),
                            # initializer=tf.get_default_graph().get_tensor_by_name(tf.get_variable_scope().name+"/weights_matrix:0"),
                            trainable=True)  # weight matrix
        self.nbparams += int(nin_ * size)

        if weight_normalization:
            self.weightnormed = True
            self.g = tf.get_variable(
                shape=[size],
                                name="weight_normalization_g",
                                # initializer=tf.constant_initializer(value=1.0, dtype="float32"),
                                # initializer=tf.get_default_graph().get_tensor_by_name(tf.get_variable_scope().name+"/weight_normalization_g:0"),
                                trainable=True)
            self.nbparams += int(size)
            self.scaled_matrix = tf.nn.l2_normalize(self.w, dim=0, name="weight_normalization_scaled_matrix")
            self.flops += size*(2*nin_-1) # clomputation of ||v|| (size comptuation of inner product of vector of size nin_)
            self.flops += 2*nin_-1  # division by ||v|| (matrix vector product)
            self.w = tf.multiply(self.scaled_matrix, self.g, name="weight_normalization_weights")
            self.flops += 2*nin_-1  # multiplication by g (matrix vector product)

        if guided_dropconnect_mask is not None:
            #TODO implement it
            pass
        self.res = tf.matmul(self.input, self.w, name="multiplying_weight_matrix")
        self.flops += 2*nin_*size-size

        if bias:
            self.bias = True
            self.b = tf.get_variable(
                shape=[size],
                                # initializer=tf.constant_initializer(value=0.0, dtype="float32"),
                                # initializer=tf.get_default_graph().get_tensor_by_name(tf.get_variable_scope().name+"/bias:0"),
                                name="bias",
                                trainable=True)
            self.nbparams += int(size)
            self.res = tf.add(self.res, self.b, name="adding_bias")
            self.flops += size # vectors addition of size "size"

        if relu:
            self.res = tf.nn.relu(self.res, name="applying_relu")
            self.flops += size  # we consider relu of requiring 1 computation per number (one max)

        if keep_prob is not None:
            self.res = tf.nn.dropout(self.res, keep_prob=keep_prob, name="applying_dropout")
            # we consider that generating random number count for 1 operation
            self.flops += size  # generate the "size" real random numbers
            self.flops += size  # building the 0-1 vector of size "size" (thresholding "size" random values)
            self.flops += size  # element wise multiplication with res

    def initwn(self, sess, scale_init=1.0):
        """
        initialize the weight normalization as describe in https://arxiv.org/abs/1602.07868
        don't do anything if the weigth normalization have not been "activated"
        :param sess: the tensorflow session
        :param scale_init: the initial scale
        :return: 
        """
        if not self.weightnormed:
            return
        # input = sess.run(input)
        with tf.variable_scope("init_wn_layer"):
            m_init, v_init = sess.run(tf.nn.moments(tf.matmul(self.input, self.w), [0]))
            # pdb.set_trace()
            sess.run(tf.assign(self.g, scale_init/tf.sqrt(v_init + 1e-10), name="weigth_normalization_init_g"))
            if self.bias:
                sess.run(tf.assign(self.b, -m_init*scale_init, name="weigth_normalization_init_b"))


class ResidualBlock:
    def __init__(self, input, size, relu=False, bias=True, guided_dropconnect_mask=None, weight_normalization=False, keep_prob=None):
        """
        for weight normalization see https://arxiv.org/abs/1602.07868
        for counting the flops of operations see https://mediatum.ub.tum.de/doc/625604/625604
        this block is insipired from https://arxiv.org/abs/1603.05027 :
        X -> Bn(.) -> Relu(.) -> W * . -> Bn(.) -> Relu(.) -> W_2 * . -> X + .
        with "." being the output of the previous computation
        Bn() -> batch normalization (currently unused)
        Relu(.) -> rectifier linear unit
        * -> matrix product
        
        dropout (regular) is done at the end of the comptuation
        
        the number of input and number of output is the same. Size is just the intermediate size
        
        :param input: input of the layer 
        :param size: layer size (number of layer after "X -> Bn(.) -> Relu(.) -> W * .")
        :param relu: do you use relu ? (at the end, just before standard dropout)
        :param bias: do you add bias ?
        :param guided_dropconnect_mask: tensor of the mask matrix  #TODO 
        :param weight_normalization: do you use weight normalization (see https://arxiv.org/abs/1602.07868)
        :param keep_prob: a scalar tensor for dropout layer (None if you don't want to use it)
        """
        self.input = input
        self.weightnormed = weight_normalization

        self.res = input
        self.flops = 0
        self.nbparams = 0

        # treating "-> Bn() -> Relu()"
        if relu:
            self.res = tf.nn.relu(self.res, name="first_relu")
            self.flops += int(self.res.shape()[1])

        #treating "-> W * . -> Bn(.) -> Relu(.)"
        self.first_layer = DenseLayer(self.res, size, relu=True, bias=bias,
                                     guided_dropconnect_mask=guided_dropconnect_mask,
                                     weight_normalization=weight_normalization,
                                     keep_prob=None)
        self.flops += self.first_layer.flops
        self.nbparams += self.first_layer.nbparams
        self.res = self.first_layer.res

        # treating "-> W_2 * . "
        self.second_layer = DenseLayer(self.res, input.shape()[1], relu=False, bias=bias,
                                       guided_dropconnect_mask=guided_dropconnect_mask,
                                       weight_normalization=weight_normalization,
                                       keep_prob=None)
        self.flops += self.second_layer.flops
        self.nbparams += self.second_layer.nbparams

        # treating "-> X + ."
        self.res = self.second_layer.res + input
        self.flops += int(self.res.shape()[1])

        if relu:
            self.res = tf.nn.relu(self.res, name="applying_relu")
            self.flops += size  # we consider relu of requiring 1 computation per number (one max)

        if keep_prob is not None:
            #TODO : copy pasted from DenseLayer
            self.res = tf.nn.dropout(self.res, keep_prob=keep_prob, name="applying_dropout")
            # we consider that generating random number count for 1 operation
            self.flops += size  # generate the "size" real random numbers
            self.flops += size  # building the 0-1 vector of size "size" (thresholding "size" random values)
            self.flops += size  # element wise multiplication with res


    def initwn(self, sess, scale_init=1.0):
        """
        initialize the weight normalization as describe in https://arxiv.org/abs/1602.07868
        don't do anything if the weigth normalization have not been "activated"
        :param sess: the tensorflow session
        :param scale_init: the initial scale
        :return: nothing
        """
        if not self.weightnormed:
            return

        self.first_layer.initwn(sess=sess, scale_init=scale_init)
        self.second_layer.initwn(sess=sess, scale_init=scale_init)


class DenseBlock:
    def __init__(self, input, relu=False, bias=True, guided_dropconnect_mask=None, weight_normalization=False,
                 keep_prob=None, nblayer=2):
        """
        for weight normalization see https://arxiv.org/abs/1602.07868
        for counting the flops of operations see https://mediatum.ub.tum.de/doc/625604/625604
        
        this block is insipired from 
        https://www.researchgate./publication/306885833_Densely_Connected_Convolutional_Networks :
        
        dropout (regular) is done at the end of the comptuation
        
        the size of each layer should be the same. That's why there is no "sizes" parameter.
        
        :param input: input of the layer 
        :param relu: do you use relu ? (at the end, just before standard dropout)
        :param bias: do you add bias ?
        :param guided_dropconnect_mask: tensor of the mask matrix  #TODO 
        :param weight_normalization: do you use weight normalization (see https://arxiv.org/abs/1602.07868)
        :param keep_prob: a scalar tensor for dropout layer (None if you don't want to use it)
        :param nblayer: the number of layer in the dense block
        """
        self.input = input
        self.weightnormed = weight_normalization
        size = int(input.shape()[1])
        self.res = input
        self.flops = 0
        self.nbparams = 0

        self.layers = []
        for i in range(nblayer):
            tmp_layer = DenseLayer(self.res, size, relu=True, bias=bias,
                                   guided_dropconnect_mask=guided_dropconnect_mask,
                                   weight_normalization=weight_normalization,
                                   keep_prob=None)
            self.flops += tmp_layer.flops
            self.nbparams += tmp_layer.nbparams
            self.res = tmp_layer.res
            with tf.variable_scope("short_connections_densely_connected"):
                for l in self.layers:
                    self.res = self.res + l.res
                    self.flops += size
            self.layers.append(tmp_layer)

        if relu:
            self.res = tf.nn.relu(self.res, name="applying_relu")
            self.flops += size  # we consider relu of requiring 1 computation per number (one max)

        if keep_prob is not None:
            #TODO : copy pasted from DenseLayer
            self.res = tf.nn.dropout(self.res, keep_prob=keep_prob, name="applying_dropout")
            # we consider that generating random number count for 1 operation
            self.flops += size  # generate the "size" real random numbers
            self.flops += size  # building the 0-1 vector of size "size" (thresholding "size" random values)
            self.flops += size  # element wise multiplication with res

    def initwn(self, sess, scale_init=1.0):
        """
        initialize the weight normalization as describe in https://arxiv.org/abs/1602.07868
        don't do anything if the weigth normalization have not been "activated"
        :param sess: the tensorflow session
        :param scale_init: the initial scale
        :return: nothing
        """
        if not self.weightnormed:
            return
        for l in self.layers:
            l.initwn(sess=sess, scale_init=scale_init)


class NNFully:
    def __init__(self, input, outputsize, layersizes=(100,), weightnorm=False, bias=True):
        """
        Most classical form of neural network,
        It takes intput as input, add hidden layers of sizes in layersizes.
        Then add 
        Infos:
            - len(layersizes) is the number of hidden layer
            - layersizes[i] is the size of the ith hidden layer
            - for a linear network, call with layersizes=[]
        :param input; the tensorflow input node
        :param outputsize: size of the output of this layer
        :param layersizes: the sizes of each layer (length= number of layer)
        :param weightnorm: do you want to use weightnormalization ? (see https://arxiv.org/abs/1602.07868)
        :param bias: do you want to add a bias in your computation
        """

        # TODO
        reuse = False
        graphtoload = None
        # bias = True

        self.nb_layer = len(layersizes)
        self.layers = []

        z = input
        #hidden layers
        for i, ls in enumerate(layersizes):
            # if size of input = layer size, we still apply guided dropout!
            with tf.variable_scope("dense_layer_{}".format(i), reuse=reuse):
                new_layer = DenseLayer(input=z, size=ls, relu=True, bias=bias, guided_dropconnect_mask=None,
                                       weight_normalization=weightnorm)
            self.layers.append(new_layer)
            z = new_layer.res

        # output layer
        self.output = None
        self.pred = None
        with tf.variable_scope("last_dense_layer", reuse=reuse):
            self.output = DenseLayer(input=z, size=outputsize, relu=False, bias=bias,
                                     guided_dropconnect_mask=None, weight_normalization=weightnorm)
            self.pred = tf.identity(self.output.res, name="output")

    def getnbparam(self):
        """
        :return: the number of trainable parameters of the neural network build 
        """
        res = 0
        for el in self.layers:
            res += el.nbparams
        res += self.output.nbparams
        return res

    def getflop(self):
        """
        flops are computed using formulas in https://mediatum.ub.tum.de/doc/625604/625604
        it takes into account both multiplication and addition. Results are given for a minibatch of 1 example.
        :return: the number of flops of the neural network build 
        """
        res = 0
        for el in self.layers:
            res += el.flops
        res += self.output.flops
        return res

    def initwn(self, sess):
        """
        Initialize the weights for weight normalization
        :param sess: a tensorflow session
        :return: 
        """
        for el in self.layers:
            el.initwn(sess=sess)
        self.output.initwn(sess=sess)

if __name__ == "__main__":
    # TODO : code some sort of test for guided dropout stuff
    input = np.ndarray([1.,2.,3.,4.,5.],shape=[5,1],dtype="float32")
    output = np.ndarray([10.,10.,10.],shape=[5,1],dtype="float32")
