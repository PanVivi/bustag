% rebase('base.tpl', title='V2 状态', path=path)
<div class="container">
 <a href="/v2">返回推荐</a>
 <p>训练、重评分和同步在后台运行。模型或标签映射变化时请重新训练。收藏辅助默认关闭，等待真实消融验收。</p>
 % for kind,label in [('train','模型对照并训练'),('rescore','重新评分全部作品'),('sync','同步已授权 Emby')]:
 <form method="post" action="/v2/job/{{kind}}" class="my-2"><input type="hidden" name="csrf" value="{{csrf}}"><button>{{label}}</button></form>
 % end
 <h5>样本统计</h5><pre>{{stats}}</pre>
 <h5>后台任务</h5><pre>{{jobs}}</pre>
 <h5>片库快照</h5><pre>{{inventory}}</pre>
 <h5>当前模型与验证限制</h5>
 % for row in manifest:
 <pre style="white-space:pre-wrap">{{row['manifest_json']}}</pre>
 % end
</div>
