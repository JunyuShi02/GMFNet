# %%
# code by Tae Hwan Jung(Jeff Jung) @graykode, Derek Miller @dmmiller612
# Reference : https://github.com/jadore801120/attention-is-all-you-need-pytorch
#           https://github.com/JayParks/transformer
import numpy as np
import torch
import torch.nn as nn
from torch.nn import Parameter


class ScaledDotProductAttention(nn.Module):

    def __init__(self, d_k):
        super(ScaledDotProductAttention, self).__init__()
        self.d_k = d_k

    def forward(self, Q, K, V):
        scores = torch.matmul(Q, K.transpose(-1, -2)) / np.sqrt(
            self.d_k)  # scores : [batch_size x n_heads x len_q(=len_k) x len_k(=len_q)]
        attn = nn.Softmax(dim=-1)(scores)
        context = torch.matmul(attn, V)
        return context, attn


class MultiHeadAttention(nn.Module):

    def __init__(self, d_model, n_heads=8, d_k=64, d_v=64):
        super(MultiHeadAttention, self).__init__()
        self.W_Q = nn.Linear(d_model, d_k * n_heads)
        self.W_K = nn.Linear(d_model, d_k * n_heads)
        self.W_V = nn.Linear(d_model, d_v * n_heads)
        self.linear = nn.Linear(n_heads * d_v, d_model)
        self.layer_norm = nn.LayerNorm(d_model)

        self.n_heads = n_heads
        self.d_k = d_k
        self.d_v = d_v

    def forward(self, Q, K, V):
        # q: [batch_size x len_q x d_model], k: [batch_size x len_k x d_model], v: [batch_size x len_k x d_model]
        residual, batch_size = Q, Q.size(0)
        # (B, S, D) -proj-> (B, S, D) -split-> (B, S, H, W) -trans-> (B, H, S, W)
        q_s = self.W_Q(Q).view(batch_size, -1, self.n_heads, self.d_k).transpose(1, 2)  # q_s: [batch_size x n_heads x len_q x d_k]
        k_s = self.W_K(K).view(batch_size, -1, self.n_heads, self.d_k).transpose(1, 2)  # k_s: [batch_size x n_heads x len_k x d_k]
        v_s = self.W_V(V).view(batch_size, -1, self.n_heads, self.d_v).transpose(1, 2)  # v_s: [batch_size x n_heads x len_k x d_v]

        context, attn = ScaledDotProductAttention(d_k=self.d_k)(q_s, k_s, v_s)
        context = context.transpose(1, 2).contiguous().view(batch_size, -1, self.n_heads * self.d_v)  # context: [batch_size x len_q x n_heads * d_v]
        output = self.linear(context)
        return self.layer_norm(output + residual), attn  # output: [batch_size x len_q x d_model]


class PoswiseFeedForwardNet(nn.Module):

    def __init__(self, d_model, d_ff=1024):
        super(PoswiseFeedForwardNet, self).__init__()
        self.conv1 = nn.Conv1d(in_channels=d_model, out_channels=d_ff, kernel_size=1)
        self.conv2 = nn.Conv1d(in_channels=d_ff, out_channels=d_model, kernel_size=1)
        self.layer_norm = nn.LayerNorm(d_model)

    def forward(self, inputs):
        residual = inputs  # inputs : [batch_size, len_q, d_model]
        output = nn.ReLU()(self.conv1(inputs.transpose(1, 2)))
        output = self.conv2(output).transpose(1, 2)
        return self.layer_norm(output + residual)


class EncoderLayer(nn.Module):

    def __init__(self, d_model, n_heads=8, d_k=64, d_v=64, d_ff=1024):
        super(EncoderLayer, self).__init__()
        self.enc_self_attn = MultiHeadAttention(d_model=d_model, n_heads=n_heads, d_k=d_k, d_v=d_v)
        self.pos_ffn = PoswiseFeedForwardNet(d_model=d_model, d_ff=d_ff)

    def forward(self, enc_inputs):
        enc_outputs, attn = self.enc_self_attn(enc_inputs, enc_inputs, enc_inputs)  # enc_inputs to same Q,K,V
        enc_outputs = self.pos_ffn(enc_outputs)  # enc_outputs: [batch_size x len_q x d_model]
        return enc_outputs, attn


class DecoderLayer(nn.Module):

    def __init__(self, d_model, n_heads=8, d_k=64, d_v=64, d_ff=1024):
        super(DecoderLayer, self).__init__()
        self.dec_self_attn = MultiHeadAttention(d_model=d_model, n_heads=n_heads, d_k=d_k, d_v=d_v)
        self.dec_enc_attn = MultiHeadAttention(d_model=d_model, n_heads=n_heads, d_k=d_k, d_v=d_v)
        self.pos_ffn = PoswiseFeedForwardNet(d_model=d_model, d_ff=d_ff)

    def forward(self, dec_inputs, enc_outputs):
        dec_outputs, dec_self_attn = self.dec_self_attn(dec_inputs, dec_inputs, dec_inputs)
        dec_outputs, dec_enc_attn = self.dec_enc_attn(dec_outputs, enc_outputs, enc_outputs)
        dec_outputs = self.pos_ffn(dec_outputs)
        return dec_outputs, dec_self_attn, dec_enc_attn


class Encoder(nn.Module):

    def __init__(self, d_model, n_layers=3, n_heads=8, d_k=64, d_v=64, d_ff=1024):
        super(Encoder, self).__init__()
        # self.pos_emb = nn.Embedding.from_pretrained(get_sinusoid_encoding_table(src_len+1, d_model),freeze=True)
        self.layers = nn.ModuleList(
            [EncoderLayer(d_model=d_model, n_heads=n_heads, d_k=d_k, d_v=d_v, d_ff=d_ff) for _ in range(n_layers)])

    def forward(self, enc_outputs):  # enc_inputs : [batch_size x source_len]
        enc_self_attns = []
        for layer in self.layers:
            enc_outputs, enc_self_attn = layer(enc_outputs)
            enc_self_attns.append(enc_self_attn)
        return enc_outputs, enc_self_attns


class Decoder(nn.Module):

    def __init__(self, d_model, n_layers=3, n_heads=8, d_k=64, d_v=64, d_ff=1024):
        super(Decoder, self).__init__()
        self.layers = nn.ModuleList(
            [DecoderLayer(d_model=d_model, n_heads=n_heads, d_k=d_k, d_v=d_v, d_ff=d_ff) for _ in range(n_layers)])

    def forward(self, dec_outputs, enc_inputs, enc_outputs):  # dec_inputs : [batch_size x target_len]

        dec_self_attns, dec_enc_attns = [], []
        for layer in self.layers:
            dec_outputs, dec_self_attn, dec_enc_attn = layer(dec_outputs, enc_outputs)
            dec_self_attns.append(dec_self_attn)
            dec_enc_attns.append(dec_enc_attn)
        return dec_outputs, dec_self_attns, dec_enc_attns


class Transformer(nn.Module):

    def __init__(self, d_input, d_model, d_output, n_layers=3, n_heads=8, d_k=64, d_v=64, d_ff=1024):
        super(Transformer, self).__init__()
        self.enc_embed = nn.Linear(d_input, d_model)
        self.encoder = Encoder(d_model, n_layers=n_layers, n_heads=n_heads, d_k=d_k, d_v=d_v, d_ff=d_ff)
        # self.decoder = Decoder(d_model, n_layers=n_layers, n_heads=n_heads, d_k=d_k, d_v=d_v, d_ff=d_ff)

        self.dec_embed = nn.Linear(d_input, d_model)
        self.dec_proj = nn.Linear(d_model, d_output, bias=False)

    def forward(self, enc_inputs,):

        # dec_inputs = enc_inputs[:, -1, :].unsqueeze(1)
        # dec_inputs = dec_inputs.repeat(1, outputs_len, 1)
        # dec_inputs = self.dec_embed(dec_inputs)

        enc_inputs = self.enc_embed(enc_inputs)
        enc_outputs, enc_self_attns = self.encoder(enc_inputs)

        # dec_outputs, dec_self_attns, dec_enc_attns = self.decoder(dec_inputs, enc_inputs, enc_outputs)

        #dec_logits = self.dec_proj(enc_outputs)  # dec_logits : [batch_size x src_vocab_size x tgt_vocab_size]

        # return dec_logits.view(-1, dec_logits.size(-1)), enc_self_attns, dec_self_attns, dec_enc_attns
        # return dec_logits
        return enc_outputs


if __name__ == '__main__':

    enc_inputs = torch.ones((32, 50, 66))

    model = Transformer(d_input=66, d_model=256, d_output=66, n_layers=3, n_heads=8, d_k=32, d_v=32, d_ff=1024)

    outputs = model(enc_inputs, 10)

    print(outputs.shape)

# def get_sinusoid_encoding_table(n_position, d_model):
#     def cal_angle(position, hid_idx):
#         return position / np.power(10000, 2 * (hid_idx // 2) / d_model)
#     def get_posi_angle_vec(position):
#         return [cal_angle(position, hid_j) for hid_j in range(d_model)]
#
#     sinusoid_table = np.array([get_posi_angle_vec(pos_i) for pos_i in range(n_position)])
#     sinusoid_table[:, 0::2] = np.sin(sinusoid_table[:, 0::2])  # dim 2i
#     sinusoid_table[:, 1::2] = np.cos(sinusoid_table[:, 1::2])  # dim 2i+1
#     return torch.FloatTensor(sinusoid_table)
