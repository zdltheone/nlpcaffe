#!/usr/bin/env python
import caffe_pb2
from caffe_pb2 import NetParameter, LayerParameter, DataParameter

import sys
import lmdb
import random
from caffe_pb2 import Datum
import subprocess

n = 30
vocab_size = 10003
rand_skip = 11 * 10 ** 6
train_batch_size = 64

def make_data():
    for phase in ['valid', 'test']:
        db_name = './models/rnn/rnn_%s_db' % phase
        subprocess.call(['rm', '-r', db_name])
        env = lmdb.open(db_name, map_size=2147483648*8)

        unknown_symbol = vocab_size - 3
        start_symbol = vocab_size - 2
        zero_symbol = vocab_size - 1

        allX = []
        with open('/home/stewartr/data/zhen/%s.40k.id.en' % phase, 'r') as f: 
        #with open('/home/stewartr/data/simple-examples/%s_indices.txt' % phase, 'r') as f: 
            for line in f.readlines():
                allX.append([int(x) for x in line.split(' ')])
                #allX.append([int(x) for x in line.split(',')])
        random.shuffle(allX)
        assert phase != 'train' or len(allX) > rand_skip

        def vocab_transform(x):
            return x if x < unknown_symbol else unknown_symbol

        with env.begin(write=True) as txn:
            for i, values in enumerate(allX):
                mod_values = map(vocab_transform, values[:n]) + [zero_symbol] * (n - len(values[:n]))
                datum = Datum()
                datum.channels = 2 * n
                datum.width = 1
                datum.height = 1
                if i % 100 == 0:
                    sys.stderr.write('%s\r' % i); sys.stderr.flush()
                for j in range(n):
                    if j == 0:
                        datum.float_data.append(start_symbol)
                    else:
                        datum.float_data.append(mod_values[j - 1])
                for j in range(n):
                    datum.float_data.append(mod_values[j])
                key = str(i)
                txn.put(key, datum.SerializeToString())

def display_layer(net, name):
    layer = net.layers.add()
    layer.name = 'display_%s' % name
    layer.top.append('display_%s' % name)
    layer.bottom.append(name)
    layer.bottom.append(name)
    layer.type = LayerParameter.ELTWISE
    layer.eltwise_param.coeff.append(0.5)
    layer.eltwise_param.coeff.append(0.5)

def add_weight_filler(param):
    param.type = 'uniform'
    param.min = -0.1
    param.max = 0.1

def get_net(deploy, batch_size):
    net = NetParameter()
    lstm_num_cells = 250
    wordvec_length = 200

    if not deploy:
        train_data = net.layers.add()
        train_data.type = LayerParameter.DATA
        train_data.name = "data"
        train_data.top.append(train_data.name)
        train_data.data_param.source = 'models/rnn/rnn_train_db'
        train_data.data_param.backend = DataParameter.LMDB
        train_data.data_param.batch_size = batch_size
        train_data.data_param.rand_skip = rand_skip
        # train_data_rule = train_data.include.add()
        # train_data_rule.phase = caffe_pb2.TRAIN

    data_slice_layer = net.layers.add()
    data_slice_layer.name = "data_slice_layer"
    data_slice_layer.type = LayerParameter.SLICE
    data_slice_layer.slice_param.slice_dim = 1
    data_slice_layer.bottom.append('data')
    data_slice_layer.top.append('words')

    wordvec_layer = net.layers.add()
    wordvec_layer.name = "wordvec_layer"
    wordvec_layer.type = LayerParameter.WORDVEC
    wordvec_layer.bottom.append('words')
    wordvec_layer.top.append(wordvec_layer.name)
    wordvec_layer.wordvec_param.dimension = wordvec_length
    wordvec_layer.wordvec_param.vocab_size = vocab_size
    add_weight_filler(wordvec_layer.wordvec_param.weight_filler)


    input_slice_layer = net.layers.add()
    input_slice_layer.name = "input_slice_layer"
    input_slice_layer.type = LayerParameter.SLICE
    input_slice_layer.slice_param.slice_dim = 0
    input_slice_layer.bottom.append('wordvec_layer')

    for i in range(n):
        data_slice_layer.top.append('target%d' % i)
        data_slice_layer.slice_param.slice_point.append(n + i)

        input_slice_layer.top.append('wordvec%d' % i)
        if i != 0:
            input_slice_layer.slice_param.slice_point.append(i * batch_size)

        if i == 0:
            dummy_layer = net.layers.add()
            dummy_layer.name = 'dummy_layer'
            dummy_layer.top.append(dummy_layer.name)
            dummy_layer.type = LayerParameter.DUMMY_DATA
            dummy_layer.dummy_data_param.num.append(batch_size)
            dummy_layer.dummy_data_param.channels.append(lstm_num_cells)
            dummy_layer.dummy_data_param.height.append(1)
            dummy_layer.dummy_data_param.width.append(1)

            dummy_mem_cell = net.layers.add()
            dummy_mem_cell.name = 'dummy_mem_cell'
            dummy_mem_cell.top.append(dummy_mem_cell.name)
            dummy_mem_cell.type = LayerParameter.DUMMY_DATA
            dummy_mem_cell.dummy_data_param.num.append(batch_size)
            dummy_mem_cell.dummy_data_param.channels.append(lstm_num_cells)
            dummy_mem_cell.dummy_data_param.height.append(1)
            dummy_mem_cell.dummy_data_param.width.append(1)


        concat_layer0 = net.layers.add()
        concat_layer0.name = 'concat0_layer%d' % i
        lstm_layer0 = net.layers.add()
        lstm_layer0.name = 'lstm0_layer%d' % i

        for j, (concat_layer, lstm_layer) in enumerate([(concat_layer0, lstm_layer0)]):
            concat_layer.top.append(concat_layer.name)
            concat_layer.type = LayerParameter.CONCAT
            concat_layer.bottom.append('wordvec%d' % i)
            if j == 1:
                concat_layer.bottom.append('lstm0_layer%d' % i)
            if i == 0:
                concat_layer.bottom.append(dummy_layer.name)
            else:
                concat_layer.bottom.append('lstm%d_layer%d' % (j, i - 1))

            lstm_layer.type = LayerParameter.LSTM
            lstm_layer.lstm_param.num_cells = lstm_num_cells

            add_weight_filler(lstm_layer.lstm_param.input_weight_filler)
            add_weight_filler(lstm_layer.lstm_param.input_gate_weight_filler)
            add_weight_filler(lstm_layer.lstm_param.forget_gate_weight_filler)
            add_weight_filler(lstm_layer.lstm_param.output_gate_weight_filler)

            for k in range(4):
                lstm_layer.param.append('lstm%d_param%d' % (j, k))
            lstm_layer.top.append('lstm%d_layer%d' % (j, i))
            lstm_layer.top.append('lstm%d_mem_cell%d' % (j, i))
            lstm_layer.bottom.append('concat%d_layer%d' % (j, i))
            if i == 0:
                lstm_layer.bottom.append('dummy_mem_cell')
            else:
                lstm_layer.bottom.append('lstm%d_mem_cell%d' % (j, i - 1))

        #dropout_layer = net.layers.add()
        #dropout_layer.name = "dropout_layer%d" % i
        #dropout_layer.top.append(dropout_layer.name)
        #dropout_layer.bottom.append('lstm0_layer%d' % i)
        #dropout_layer.type = LayerParameter.DROPOUT
        #dropout_layer.dropout_param.dropout_ratio = 0.5

        inner_product_layer = net.layers.add()
        inner_product_layer.name = "inner_product%d" % i
        inner_product_layer.top.append(inner_product_layer.name)
        #inner_product_layer.bottom.append('dropout_layer%d' % i)
        inner_product_layer.bottom.append('lstm0_layer%d' % i)
        #dropout_layer.bottom.append(% i)
        inner_product_layer.type = LayerParameter.INNER_PRODUCT
        inner_product_layer.blobs_lr.append(1)
        inner_product_layer.blobs_lr.append(0)
        inner_product_layer.weight_decay.append(1)
        inner_product_layer.weight_decay.append(0)
        inner_product_layer.inner_product_param.num_output = vocab_size
        add_weight_filler(inner_product_layer.inner_product_param.weight_filler)
        inner_product_layer.inner_product_param.bias_filler.type = "constant"
        inner_product_layer.inner_product_param.bias_filler.value = 0.0
        inner_product_layer.param.append('inner_product_weight')
        inner_product_layer.param.append('inner_product_bias')

        
        if deploy:
            prob_layer = net.layers.add()
            prob_layer.name = "prob%d" % i
            prob_layer.type = LayerParameter.SOFTMAX
            prob_layer.bottom.append("inner_product%d" % i)
            prob_layer.top.append("prob%d" % i)
        else:
            loss_layer = net.layers.add()
            i_str = ''.join(['0'] * (len(str(n)) - len(str(i)))) + str(i)
            loss_layer.name = "loss%s" % i_str
            loss_layer.type = LayerParameter.SOFTMAX_LOSS
            loss_layer.bottom.append("inner_product%d" % i)
            loss_layer.bottom.append("target%d" % i)
            loss_layer.top.append(loss_layer.name)

        if i == n - 1:
            silence_layer = net.layers.add()
            silence_layer.name = "silence%d" % i
            silence_layer.type = LayerParameter.SILENCE
            silence_layer.bottom.append("lstm0_mem_cell%d" % i)

    return net

def main():
    if '--make_data' in sys.argv:
        make_data()

    with open('./models/rnn/train_val.prototxt', 'w') as f:
        f.write('name: "RussellNet"\n')
        f.write(str(get_net(False, train_batch_size)));

    with open('./models/rnn/deploy.prototxt', 'w') as f:
        f.write('name: "RussellNet"\n')
        f.write('''
input: "data"
input_dim: 10
input_dim: %s
input_dim: 1
input_dim: 1

''' % (2 * n))
        f.write(str(get_net(True, 10)))
main()
