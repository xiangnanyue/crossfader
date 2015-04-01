import math
import random
import numpy
import json
import theano
import theano.tensor as T
from theano.tensor.nnet import sigmoid
import pylab

def floatX(x):
    return numpy.asarray(x, dtype=theano.config.floatX)

srng = theano.tensor.shared_randomstreams.RandomStreams()

def get_splits(headers, data, bins):
    values = [[v[header] for v in data if header in v] for header in headers]

    splits = []
    for j in xrange(len(headers)):
        lo, hi = numpy.percentile(values[j], 1.0), numpy.percentile(values[j], 99.0)
        print headers[j], lo, hi
        for bin in xrange(bins):
            x_split = lo + (bin + 1) * (hi - lo) * 1. / bins
            splits.append((j, x_split))
    return splits

        
def get_row(headers, K, data_row, splits, headers_keep=None):
    # V: values
    V_row = numpy.zeros(K, dtype=theano.config.floatX)
    # M: what values are missing
    M_row = numpy.zeros(K, dtype=theano.config.floatX)
    # Q: what values to predict
    Q_row = numpy.zeros(K, dtype=theano.config.floatX)

    for k, split in enumerate(splits):
        j, x_split = split
        if headers[j] not in data_row:
            M_row[k] = 1
            continue
        x = data_row[headers[j]]
        if x < x_split:
            V_row[k] = 1

        if headers_keep is not None and headers[j] not in headers_keep:
            Q_row[k] = 1

    return V_row, M_row, Q_row


def build_matrices(headers, data, D, K, splits, batch_size=100):
    V = numpy.zeros((D, K), dtype=theano.config.floatX)
    M = numpy.zeros((D, K), dtype=theano.config.floatX)
    Q = numpy.zeros((D, K), dtype=theano.config.floatX)

    for i, data_row in enumerate(random.sample(data, batch_size)):
        # How many header should we remove
        n_headers_keep = random.randint(0, len(headers))
        headers_keep = set(random.sample(headers, n_headers_keep))
        V[i], M[i], Q[i] = get_row(headers, K, data_row, splits, headers_keep)

    return V, M, Q


def W_values(n_in, n_out):
    return numpy.random.uniform(
        low=-numpy.sqrt(6. / (n_in + n_out)),
        high=numpy.sqrt(6. / (n_in + n_out)),
        size=(n_in, n_out))


def get_parameters(K):
    # Train an autoencoder to reconstruct the rows of the V matrices
    n_hidden_layers = 1
    n_hidden_units = 32
    Ws, bs = [], []
    for l in xrange(n_hidden_layers + 1):
        n_in, n_out = n_hidden_units, n_hidden_units
        if l == 0:
            n_in = K
        elif l == n_hidden_layers:
            n_out = K

        Ws.append(theano.shared(W_values(n_in, n_out)))
        gamma = 0.1 # initialize it to slightly positive so the derivative exists
        bs.append(theano.shared(numpy.ones(n_out) * gamma))

    return Ws, bs

def get_model(Ws, bs, dropout=False):
    v = T.matrix('input')
    m = T.matrix('missing')
    q = T.matrix('target')

    # Set all missing/target values to 0.5
    keep_mask = (1-m) * (1-q)
    h = keep_mask * (v * 2 - 1) # Convert to +1, -1
    
    for l in xrange(len(Ws)):
        h = T.dot(h, Ws[l]) + bs[l]

        if l < len(Ws) - 1:
            h = h * (h > 0) # relu
            if dropout:
                mask = srng.binomial(n=1, p=0.5, size=h.shape)
                h = h * mask * 2

    output = sigmoid(h)
    
    LL = v * T.log(output) + (1 - v) * T.log(1 - output)
    loss = -(q * LL).sum() / q.sum()

    return v, m, q, output, loss


def nesterov_updates(loss, all_params, learn_rate, momentum, weight_decay):
    updates = []
    all_grads = T.grad(loss, all_params)
    for param_i, grad_i in zip(all_params, all_grads):
        # generate a momentum parameter
        mparam_i = theano.shared(numpy.array(param_i.get_value()*0.))
        full_grad_i = grad_i + weight_decay * param_i
        v = momentum * mparam_i - learn_rate * full_grad_i
        w = param_i + momentum * v - learn_rate * full_grad_i
        updates.append((param_i, w))
        updates.append((mparam_i, v))
    return updates


def get_train_f(Ws, bs):
    v, m, q, output, loss = get_model(Ws, bs, dropout=False)
    updates = nesterov_updates(loss, Ws + bs, 1e-1, 0.9, 1e-4)
    return theano.function([v, m, q], loss, updates=updates)


def get_pred_f(Ws, bs):
    v, m, q, output, loss = get_model(Ws, bs, dropout=False)
    return theano.function([v, m, q], output)


def train(headers, data, plot_x=None, plot_y=None):
    D = len(data)
    K = 200 # Random splits
    bins = K / len(headers)
    K = bins * len(headers)

    print D, 'data points', K, 'random splits', bins, 'bins', K, 'features'

    splits = get_splits(headers, data, bins)

    Ws, bs = get_parameters(K)
    train_f = get_train_f(Ws, bs)
    pred_f = get_pred_f(Ws, bs)

    for iter in xrange(1000000):
        V, M, Q = build_matrices(headers, data, D, K, splits)
        print train_f(V, M, Q)
        
        if (iter + 1) % 20 == 0 and header_plot_x and header_plot_y:
            series = []
            legends = []
            cm = pylab.get_cmap('cool')
            pylab.clf()
            
            for j, x_split in splits:
                if headers[j] == header_plot_x:
                    data_row = {headers[j]: x_split}
                    V, M, Q = [x.reshape((1, K)) for x in get_row(headers, K, data_row, splits)]

                    P = pred_f(V, M, Q)
                    
                    xs = []
                    ys = []
                    for i, split in enumerate(splits):
                        j2, x2_split = split
                        if headers[j2] == header_plot_y:
                            xs.append(x2_split)
                            ys.append(P[0][i])

                    pylab.plot(xs, ys, color=cm(1.0 * len(legends) / (bins - 1)))
                    legends += ['FICO %3d' % x_split]

            # pylab.plot(*series)
            # pylab.legend(legends)
            pylab.savefig('interest_rates.png')


if __name__ == '__main__':
    data = json.load(open('stock-data.json'))

    headers = sorted(list(set([key for v in data.values() for key in v.keys()])))

    train(headers, data)
