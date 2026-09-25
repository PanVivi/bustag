% rebase('base.tpl', title='模型', path=path)

<div class="container">
 <div class="row py-3">
  <div class="col-10 offset-1">
   <div class="card">
    <div class="card-header">
     <h5 class="mb-0">推荐模型 V2</h5>
    </div>
    <div class="card-body">
     <p class="card-text">
      使用演员/分类/番号系列等标签预测兴趣分数，并让近期人工反馈权重更高。
      训练完成后会用全部人工打标数据重新拟合正式模型。
     </p>
     <a href="/do-training" class="btn btn-primary">重新训练模型</a>
    </div>

    % if defined('error_msg') and error_msg is not None:
    <div class="alert alert-danger mx-3">{{error_msg}}</div>
    % end

    % if model_scores is not None:
    <ul class="list-group list-group-flush">
     <li class="list-group-item">模型：{{model_scores.get('algorithm', '未知')}}</li>
     <li class="list-group-item">推荐准确率 Precision：{{model_scores['precision']}}</li>
     <li class="list-group-item">覆盖率 Recall：{{model_scores['recall']}}</li>
     <li class="list-group-item">综合评分 F1：{{model_scores['f1']}}</li>
     % if model_scores.get('samples') is not None:
     <li class="list-group-item">人工打标样本：{{model_scores['samples']}}</li>
     <li class="list-group-item">有效特征：{{model_scores['features']}}</li>
     <li class="list-group-item">推荐阈值：{{model_scores['threshold']}}</li>
     <li class="list-group-item">近期偏好半衰期：{{model_scores['half_life_days']}} 天</li>
     % end
    </ul>
    % else:
    <div class="card-body">
     还没有训练 V2 模型。首次升级后请手动训练一次。
    </div>
    % end
   </div>
  </div>
 </div>
</div>
