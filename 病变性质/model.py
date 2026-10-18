"""
@file model.py
@brief 病变性质判定 GCN 模型定义（v1）
       PathlogyGCN + SimpleGCNLayer + AttentionReadout
       二分类：Normal / Abnormal

核心设计:
  - 残差连接 + LayerNorm，避免深层图网络退化
  - AttentionReadout 自适应池化，替代简单 GAP
  - Dropout 正则化，防止过拟合
  - 二分类输出，由 GMM 聚类确定边界
"""

import torch
import torch.nn as nn
import torch.nn.functional as F


class SimpleGCNLayer(nn.Module):
    """
    带残差连接和 LayerNorm 的 GCN 层

    消息传递公式: H' = ReLU(LayerNorm(Adj * Linear(H))) + H (if same dim)
    """

    def __init__(self, in_features: int, out_features: int, dropout: float = 0.0):
        """
        @param in_features: 输入特征维度
        @param out_features: 输出特征维度
        @param dropout: Dropout 概率
        """
        super().__init__()
        self.linear = nn.Linear(in_features, out_features)
        self.norm = nn.LayerNorm(out_features)
        self.dropout = nn.Dropout(dropout)
        self.use_residual = (in_features == out_features)

    def forward(self, x: torch.Tensor, adj: torch.Tensor) -> torch.Tensor:
        """
        @param x: 节点特征 (N, in_features)
        @param adj: 归一化邻接矩阵 (N, N)
        @return: 更新后的节点特征 (N, out_features)
        """
        identity = x
        out = self.linear(x)
        out = torch.matmul(adj, out)
        out = self.norm(out)
        out = F.relu(out)
        out = self.dropout(out)
        if self.use_residual:
            out = out + identity
        return out


class AttentionReadout(nn.Module):
    """
    自适应注意力图池化

    为每个节点学习注意力权重，加权求和得到图级别表示：
    graph_repr = sum_i(alpha_i * h_i),  alpha = softmax(MLP(h))
    """

    def __init__(self, in_dim: int):
        """
        @param in_dim: 节点特征维度
        """
        super().__init__()
        self.attn = nn.Sequential(
            nn.Linear(in_dim, in_dim // 2),
            nn.ReLU(),
            nn.Linear(in_dim // 2, 1)
        )

    def forward(self, h: torch.Tensor) -> torch.Tensor:
        """
        @param h: 节点特征 (N, in_dim)
        @return: 图级别特征 (1, in_dim)
        """
        weights = torch.softmax(self.attn(h), dim=0)
        return torch.sum(weights * h, dim=0, keepdim=True)


class PathlogyGCN(nn.Module):
    """
    病理图卷积网络（二分类）

    输入: 每个细胞节点的14维特征（坐标+形态+纹理）
    结构: 3层GCN → AttentionReadout → 分类器
    输出: 2分类 logits（Normal / Abnormal）
    """

    def __init__(self, node_features: int = 14, hidden_dim: int = 128,
                 num_classes: int = 2, dropout: float = 0.3):
        """
        @param node_features: 输入节点特征维度
        @param hidden_dim: 隐藏层维度
        @param num_classes: 输出类别数（2 = Normal/Abnormal）
        @param dropout: Dropout 概率
        """
        super().__init__()
        self.gcn1 = SimpleGCNLayer(node_features, hidden_dim, dropout)
        self.gcn2 = SimpleGCNLayer(hidden_dim, hidden_dim, dropout)
        self.gcn3 = SimpleGCNLayer(hidden_dim, 64, dropout)

        self.readout = AttentionReadout(64)

        self.classifier = nn.Sequential(
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(32, num_classes)
        )

    def forward(self, xs: list, adjs: list) -> torch.Tensor:
        """
        批量前向传播

        @param xs: 节点特征列表 (N_i, 14)
        @param adjs: 邻接矩阵列表 (N_i, N_i)
        @return: 分类 logits (B, num_classes)
        """
        out_batch = []
        for x, adj in zip(xs, adjs):
            h = self.gcn1(x, adj)
            h = self.gcn2(h, adj)
            h = self.gcn3(h, adj)
            h_graph = self.readout(h)
            out = self.classifier(h_graph)
            out_batch.append(out)
        return torch.cat(out_batch, dim=0)


# ============================================================
# 共享常量
# ============================================================

NATURE_CLASSES = ["Normal", "Abnormal"]
NATURE_CN = {
    "Normal": "正常",
    "Abnormal": "异常",
}
