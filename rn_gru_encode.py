import datetime, pickle, random, time
from sys import stdin, stdout, stderr
import numpy as np
import theano as th
import theano.tensor as T

from rn_rnn_model import ModelParams

# TODO: add dropout between layers, *proper* embedding layer hooks
# TODO: make scaffolding for context windows (might need to involve charset)
class GRUEncode(ModelParams):
    """Multi-layer GRU network, with non-recurrent input layer E and 
    output layer V, with bias vectors of a and c, and specified number 
    of hidden layers.

    Each hidden layer has weight matrices U and W with bias vector b.

    Softmax applied to final output.
    """

    def __init__(self, hyper, epoch=0, pos=0, E=None, U=None, W=None, V=None, a=None, b=None, c=None):
        super(GRUEncode, self).__init__(hyper, epoch, pos)

        # Randomly initialize matrices if not provided
        # E, F, U, W get 3 2D matrices per layer (reset and update gates plus hidden state)
        # NOTE: as truth values of numpy arrays are ambiguous, explicit isinstance() used instead
        tE = E if isinstance(E, np.ndarray) else np.random.uniform(
            -np.sqrt(1.0/hyper.vocab_size), np.sqrt(1.0/hyper.vocab_size), 
            (hyper.vocab_size, hyper.state_size))

        tU = U if isinstance(U, np.ndarray) else np.random.uniform(
            -np.sqrt(1.0/hyper.state_size), np.sqrt(1.0/hyper.state_size), 
            (hyper.layers*3, hyper.state_size, hyper.state_size))

        tW = W if isinstance(W, np.ndarray) else np.random.uniform(
            -np.sqrt(1.0/hyper.state_size), np.sqrt(1.0/hyper.state_size), 
            (hyper.layers*3, hyper.state_size, hyper.state_size))

        tV = V if isinstance(V, np.ndarray) else np.random.uniform(
            -np.sqrt(1.0/hyper.state_size), np.sqrt(1.0/hyper.state_size), 
            (hyper.state_size, hyper.vocab_size))

        # Initialize bias matrices to zeroes
        # b gets 3x2D per layer, c is single 2D
        ta = a if isinstance(a, np.ndarray) else np.zeros(hyper.state_size)
        tb = b if isinstance(b, np.ndarray) else np.zeros((hyper.layers*3, hyper.state_size))
        tc = c if isinstance(c, np.ndarray) else np.zeros(hyper.vocab_size)

        # Shared variables
        self.E = th.shared(name='E', value=tE.astype(th.config.floatX))
        self.a = th.shared(name='a', value=ta.astype(th.config.floatX))
        self.U = th.shared(name='U', value=tU.astype(th.config.floatX))
        self.W = th.shared(name='W', value=tW.astype(th.config.floatX))
        self.b = th.shared(name='b', value=tb.astype(th.config.floatX))
        self.V = th.shared(name='V', value=tV.astype(th.config.floatX))
        self.c = th.shared(name='c', value=tc.astype(th.config.floatX))

        # rmsprop parameters
        self.mE = th.shared(name='mE', value=np.zeros_like(tE).astype(th.config.floatX))
        self.ma = th.shared(name='ma', value=np.zeros_like(ta).astype(th.config.floatX))
        self.mU = th.shared(name='mU', value=np.zeros_like(tU).astype(th.config.floatX))
        self.mW = th.shared(name='mW', value=np.zeros_like(tW).astype(th.config.floatX))
        self.mb = th.shared(name='mb', value=np.zeros_like(tb).astype(th.config.floatX))
        self.mV = th.shared(name='mV', value=np.zeros_like(tV).astype(th.config.floatX))
        self.mc = th.shared(name='mc', value=np.zeros_like(tc).astype(th.config.floatX))

        # Build Theano graph and add related attributes
        stdout.write("Compiling Theano graph and functions...")
        stdout.flush()
        time1 = time.time()
        self.__build_t__()
        time2 = time.time()
        stdout.write("done!\nCompilation took {0:.3f} s.\n".format(time2 - time1))
        stdout.flush()

    def __build_t__(self):
        """Build Theano graph and define functions."""

        # Constants(ish)
        layers = self.hyper.layers
        vocab_size = self.hyper.vocab_size
        state_size = self.hyper.state_size

        # Local bindings for convenience
        E, U, W, V, a, b, c = self.E, self.U, self.W, self.V, self.a, self.b, self.c

        # Forward propagation
        def forward_step(x_t, s_t):
            """Input vector/matrix x(t) and state matrix s(t)."""

            # Gradient clipping
            E_c = th.gradient.grad_clip(E, -5.0, 5.0)
            a_c = th.gradient.grad_clip(a, -5.0, 5.0)
            U_c = th.gradient.grad_clip(U, -5.0, 5.0)
            W_c = th.gradient.grad_clip(W, -5.0, 5.0)
            b_c = th.gradient.grad_clip(b, -5.0, 5.0)
            V_c = th.gradient.grad_clip(V, -5.0, 5.0)
            c_c = th.gradient.grad_clip(c, -5.0, 5.0)

            # Initialize state to return
            s_next = T.zeros_like(s_t)

            # Vocab-to-state encoding layer
            inout = T.tanh(T.dot(x_t, E_c) + a_c)

            # Loop over GRU layers
            for layer in range(layers):
                # 3 matrices per layer
                L = layer * 3
                # Get previous state for this layer
                s_prev = s_t[layer]
                # Update gate
                z = T.nnet.hard_sigmoid(T.dot(inout, U_c[L]) + T.dot(s_prev, W_c[L]) + b_c[L])
                # Reset gate
                r = T.nnet.hard_sigmoid(T.dot(inout, U_c[L+1]) + T.dot(s_prev, W_c[L+1]) + b_c[L+1])
                # Candidate state
                h = T.tanh(T.dot(inout, U_c[L+2]) + T.dot(r * s_prev, W_c[L+2]) + b_c[L+2])
                # New state
                s_new = (T.ones_like(z) - z) * h + z * s_prev
                s_next = T.set_subtensor(s_next[layer], s_new)
                # Update for next layer or final output (might add dropout here later)
                inout = s_new

            # Final output
            o_t = T.dot(inout, V_c) + c_c
            return o_t, s_next


        ### SINGLE-SEQUENCE TRAINING ###

        # Inputs
        x = T.matrix('x')
        y = T.matrix('y')
        s_in = T.matrix('s_in')

        def single_step(x_t, s_t):
            o_t1, s_t = forward_step(x_t, s_t)
            # Theano's softmax returns matrix, and we just want the one entry
            o_t2 = T.nnet.softmax(o_t1)[-1]
            return o_t2, s_t

        # Now get Theano to do the heavy lifting
        [o, s_seq], _ = th.scan(
            single_step, 
            sequences=x, 
            truncate_gradient=self.hyper.bptt_truncate,
            outputs_info=[None, dict(initial=s_in)])
        s_out = s_seq[-1]

        # Costs
        o_errs = T.nnet.categorical_crossentropy(o, y)
        o_err = T.sum(o_errs)
        # Should regularize at some point
        cost = o_err

        # Gradients
        dE = T.grad(cost, E)
        da = T.grad(cost, a)
        dU = T.grad(cost, U)
        dW = T.grad(cost, W)
        db = T.grad(cost, b)
        dV = T.grad(cost, V)
        dc = T.grad(cost, c)

        # rmsprop parameter updates
        learnrate = T.scalar('learnrate')
        decayrate = T.scalar('decayrate')
        mE = decayrate * self.mE + (1 - decayrate) * dE ** 2
        ma = decayrate * self.ma + (1 - decayrate) * da ** 2
        mU = decayrate * self.mU + (1 - decayrate) * dU ** 2
        mW = decayrate * self.mW + (1 - decayrate) * dW ** 2
        mb = decayrate * self.mb + (1 - decayrate) * db ** 2
        mV = decayrate * self.mV + (1 - decayrate) * dV ** 2
        mc = decayrate * self.mc + (1 - decayrate) * dc ** 2

        # Training step function
        self.train_step = th.function(
            [x, y, s_in, th.Param(learnrate, default=0.001), th.Param(decayrate, default=0.95)],
            s_out,
            updates=[
                (E, E - learnrate * dE / T.sqrt(mE + 1e-6)),
                (a, a - learnrate * da / T.sqrt(ma + 1e-6)),
                (U, U - learnrate * dU / T.sqrt(mU + 1e-6)),
                (W, W - learnrate * dW / T.sqrt(mW + 1e-6)),
                (b, b - learnrate * db / T.sqrt(mb + 1e-6)),
                (V, V - learnrate * dV / T.sqrt(mV + 1e-6)),
                (c, c - learnrate * dc / T.sqrt(mc + 1e-6)),
                (self.mE, mE),
                (self.ma, ma),
                (self.mU, mU),
                (self.mW, mW),
                (self.mb, mb),
                (self.mV, mV),
                (self.mc, mc)],
            name = 'train_step')


        ### BATCH-SEQUENCE TRAINING ###

        # Batch Inputs
        x_bat = T.tensor3('x_bat')
        y_bat = T.tensor3('y_bat')
        s_in_bat = T.tensor3('s_in_bat')

        def batch_step(x_t, s_t):
            o_t1, s_t = forward_step(x_t, s_t)
            # We can use the whole matrix from softmax for batches
            o_t2 = T.nnet.softmax(o_t1)
            return o_t2, s_t

        [o_bat, s_seq_bat], _ = th.scan(
            batch_step, 
            sequences=x_bat, 
            truncate_gradient=self.hyper.bptt_truncate,
            outputs_info=[None, dict(initial=s_in_bat)])
        s_out_bat = s_seq_bat[-1]

        # Costs
        # We have to reshape the outputs, since Theano's categorical cross-entropy
        # function will only work with matrices or vectors, not tensor3s.
        # Thus we flatten along the sequence/batch axes, leaving the prediction
        # vectors as-is, and this seems to be enough for Theano's deep magic to work.
        o_bat_flat = T.reshape(o_bat, (o_bat.shape[0] * o_bat.shape[1], -1))
        y_bat_flat = T.reshape(y_bat, (y_bat.shape[0] * y_bat.shape[1], -1))
        o_errs_bat = T.nnet.categorical_crossentropy(o_bat_flat, y_bat_flat)
        cost_bat = T.sum(o_errs_bat)

        # Gradients
        dE_bat = T.grad(cost_bat, E)
        da_bat = T.grad(cost_bat, a)
        dU_bat = T.grad(cost_bat, U)
        dW_bat = T.grad(cost_bat, W)
        db_bat = T.grad(cost_bat, b)
        dV_bat = T.grad(cost_bat, V)
        dc_bat = T.grad(cost_bat, c)

        # rmsprop parameter updates
        mE_bat = decayrate * self.mE + (1 - decayrate) * dE_bat ** 2
        ma_bat = decayrate * self.ma + (1 - decayrate) * da_bat ** 2
        mU_bat = decayrate * self.mU + (1 - decayrate) * dU_bat ** 2
        mW_bat = decayrate * self.mW + (1 - decayrate) * dW_bat ** 2
        mb_bat = decayrate * self.mb + (1 - decayrate) * db_bat ** 2
        mV_bat = decayrate * self.mV + (1 - decayrate) * dV_bat ** 2
        mc_bat = decayrate * self.mc + (1 - decayrate) * dc_bat ** 2

        # Batch training step function
        self.train_step_bat = th.function(
            [x_bat, y_bat, s_in_bat, th.Param(learnrate, default=0.001), th.Param(decayrate, default=0.95)],
            s_out_bat,
            updates=[
                (E, E - learnrate * dE_bat / T.sqrt(mE_bat + 1e-6)),
                (a, a - learnrate * da_bat / T.sqrt(ma_bat + 1e-6)),
                (U, U - learnrate * dU_bat / T.sqrt(mU_bat + 1e-6)),
                (W, W - learnrate * dW_bat / T.sqrt(mW_bat + 1e-6)),
                (b, b - learnrate * db_bat / T.sqrt(mb_bat + 1e-6)),
                (V, V - learnrate * dV_bat / T.sqrt(mV_bat + 1e-6)),
                (c, c - learnrate * dc_bat / T.sqrt(mc_bat + 1e-6)),
                (self.mE, mE_bat),
                (self.ma, ma_bat),
                (self.mU, mU_bat),
                (self.mW, mW_bat),
                (self.mb, mb_bat),
                (self.mV, mV_bat),
                (self.mc, mc_bat)],
            name = 'train_step_bat')


        ### ERROR CHECKING ###

        # Error/cost calculations
        self.errs = th.function([x, y, s_in], [o_errs, s_out])
        self.errs_bat = th.function([x_bat, y_bat, s_in_bat], [o_errs_bat, s_out_bat])
        self.err = th.function([x, y, s_in], [cost, s_out])
        self.err_bat = th.function([x_bat, y_bat, s_in_bat], [cost_bat, s_out_bat])

        # Gradient calculations
        # We'll use this at some point for gradient checking
        self.grad = th.function([x, y, s_in], [dE, da, dU, dW, db, dV, dc])


        ### SEQUENCE GENERATION ###

        x_in = T.vector('x_in')
        k = T.iscalar('k')
        temperature = T.scalar('temperature')

        rng = T.shared_randomstreams.RandomStreams(seed=int(
            np.sum(self.a.get_value()) * np.sum(self.b.get_value()) 
            * np.sum(self.c.get_value()) * 100000.0 + 123456789) % 4294967295)

        '''
        # For debug
        o_p1, s_p1 = forward_step(x_in, s_in)
        self._single_step = th.function(
            inputs=[x_in, s_in], 
            outputs=[o_p1, s_p1],
            name='_single_step')

        '''
        # Generate output sequence based on input single onehot and given state.
        # Chooses output char by multinomial, and feeds back in for next step.
        # Scaled by temperature parameter before softmax (temperature 1.0 leaves
        # softmax output unchanged).
        # Returns matrix of one-hot vectors
        def generate_step(x_t, s_t, temp):
            # Do next step
            o_t1, s_t = forward_step(x_t, s_t)

            # Get softmax
            o_t2 = T.nnet.softmax(o_t1 / temp)[-1]

            # Randomly choose by multinomial distribution
            o_rand = rng.multinomial(n=1, pvals=o_t2, dtype=th.config.floatX)

            return o_rand, s_t

        [o_chs, s_chs], genupdate = th.scan(
            fn=generate_step,
            outputs_info=[dict(initial=x_in), dict(initial=s_in)],
            non_sequences=temperature,
            n_steps=k)
        s_ch = s_chs[-1]

        self.gen_chars = th.function(
            inputs=[k, x_in, s_in, th.Param(temperature, default=0.1)], 
            outputs=[o_chs, s_ch], 
            name='gen_chars', 
            updates=genupdate)

        # Chooses output char by argmax, and feeds back in
        def generate_step_max(x_t, s_t):
            # Do next step
            o_t1, s_t1 = forward_step(x_t, s_t)

            # Get softmax
            o_t2 = T.nnet.softmax(o_t1)[-1]

            # Now find selected index
            o_idx = T.argmax(o_t2)

            # Create one-hot
            o_ret = T.zeros_like(o_t2)
            o_ret = T.set_subtensor(o_ret[o_idx], 1.0)

            return o_ret, s_t1

        [o_chms, s_chms], _ = th.scan(
            fn=generate_step_max,
            outputs_info=[dict(initial=x_in), dict(initial=s_in)],
            n_steps=k)
        s_chm = s_chms[-1]

        self.gen_chars_max = th.function(
            inputs=[k, x_in, s_in], 
            outputs=[o_chms, s_chm], 
            name='gen_chars_max')

        # Sequence generation alternative
        # Predicted next char probability 
        # (reqires recursive input to generate sequence)
        #o_next = o[-1]
        #self.predict_prob = th.function([x, s_in], [o_next, s_out])

        ### Whew, I think we're done! ###

    @classmethod
    def loadfromfile(cls, infile):
        with np.load(infile) as f:
            # Load matrices
            p, E, U, W, V, a, b, c = f['p'], f['E'], f['U'], f['W'], f['V'], f['a'], f['b'], f['c']

            # Extract hyperparams and position
            params = pickle.loads(p.tobytes())
            hyper, epoch, pos = params['hyper'], params['epoch'], params['pos']

            # Create instance
            model = cls(hyper, epoch, pos, E=E, U=U, W=W, V=V, a=a, b=b, c=c)
            if isinstance(infile, str):
                stderr.write("Loaded model parameters from {0}\n".format(infile))

            return model

    def savetofile(self, outfile):
        # Pickle non-matrix params into bytestring, then convert to numpy byte array
        pklbytes = pickle.dumps({'hyper': self.hyper, 'epoch': self.epoch, 'pos': self.pos}, 
            protocol=pickle.HIGHEST_PROTOCOL)
        p = np.fromstring(pklbytes, dtype=np.uint8)

        # Now save params and matrices to file
        try:
            np.savez(outfile, p=p, 
                E=self.E.get_value(), 
                U=self.U.get_value(), 
                W=self.W.get_value(), 
                V=self.V.get_value(), 
                a=self.a.get_value(), 
                b=self.b.get_value(), 
                c=self.c.get_value())
        except OSError as e:
            raise e
        else:
            if isinstance(outfile, str):
                stderr.write("Saved model parameters to {0}\n".format(outfile))

    def freshstate(self, batchsize=0):
        if batchsize > 0:
            return np.zeros([self.hyper.layers, batchsize, self.hyper.state_size], dtype=th.config.floatX)
        else:
            return np.zeros([self.hyper.layers, self.hyper.state_size], dtype=th.config.floatX)

