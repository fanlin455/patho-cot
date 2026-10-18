# P0 结果：冻结 Phikon-v2 + 线性探针 vs 现有 ViT-B/16

- 基线：ViT-B/16 (现有系统, 微调) = **94.18%**（设计文档记载，791 张测试集）
- 最佳方法：**kNN5-cls** = **99.75%**（+5.57pp）

| 方法 | 池化 | 测试集准确率 | 对比基线 |
|---|---|---|---|
| kNN5-cls | cls | 99.75% | +5.57pp |
| LogReg-cls | cls | 98.99% | +4.81pp |
| LogReg-mean | mean | 97.85% | +3.67pp |
| kNN5-mean | mean | 97.72% | +3.54pp |
| kNN20-cls | cls | 96.46% | +2.28pp |
| kNN20-mean | mean | 93.43% | -0.75pp |

## 各类别准确率（最佳方法）

| 器官 | 测试样本数 | 准确率 |
|---|---|---|
| Uterus | 20 | 95.00% |
| Breast | 259 | 99.61% |
| Adrenal-gland | 45 | 100.00% |
| Bile-duct | 44 | 100.00% |
| Bladder | 5 | 100.00% |
| Cervix | 26 | 100.00% |
| Colon | 152 | 100.00% |
| Esophagus | 38 | 100.00% |
| HeadNeck | 34 | 100.00% |
| Kidney | 10 | 100.00% |
| Liver | 19 | 100.00% |
| Lung | 23 | 100.00% |
| Ovarian | 13 | 100.00% |
| Pancreatic | 19 | 100.00% |
| Prostate | 15 | 100.00% |
| Skin | 12 | 100.00% |
| Stomach | 15 | 100.00% |
| Testis | 19 | 100.00% |
| Thyroid | 23 | 100.00% |