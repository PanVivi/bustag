% rebase('base.tpl', title='个人推荐 V2', path=path)
<div class="container">
 <nav><a href="/v2?entry=discover">发现新片</a> · <a href="/v2?entry=local">本地片库推荐</a> · <a href="/v2?entry=review">演员冲突待确认</a> · <a href="/v2/manage">偏好与身份确认</a> · <a href="/v2/status">训练与同步状态</a></nav>
 <p>人工演员偏好优先。匹配分数并非校准的喜欢概率；缺失标签不代表不喜欢。</p>
 % for work in items:
 <article class="card my-3"><div class="card-body">
 <h5>{{work['code'] or '待确认番号'}} · {{work['title']}}</h5>
 <p>{{work['queue']}} · 匹配分数 {{'%.3f' % work['score']}} · {{'；'.join(work['reasons'])}}</p>
 <form method="post" action="/v2/feedback/{{work['work_id']}}">
  <input type="hidden" name="csrf" value="{{csrf}}">
  <button name="value" value="1">喜欢这部作品</button><button name="value" value="0">不喜欢这部作品</button>
 </form>
 % for actor in work['actors']:
 <form method="post" action="/v2/actor/{{actor['actor_id']}}" class="my-2">
  <input type="hidden" name="csrf" value="{{csrf}}">
  <label>{{actor['name']}} · 人工状态</label>
  <select name="state">
  % for value, label in [('like','喜欢'),('dislike','不喜欢'),('pending','待确认')]:
   <option value="{{value}}" {{'selected' if actor['state']==value else ''}}>{{label}}</option>
  % end
  </select><button>保存</button>
 </form>
 % end
 <details><summary>标签与人工纠错</summary>
 <p>作品 ID：{{work['work_id']}}</p>
 % for tag in work['tags']:
 <form method="post" action="/v2/tag/{{work['work_id']}}/{{tag['tag_id']}}">
  <input type="hidden" name="csrf" value="{{csrf}}">
  {{tag['category']}} / {{tag['name']}} · {{'采用' if tag['enabled'] else '已排除'}}
  <button name="enabled" value="{{0 if tag['enabled'] else 1}}">{{'排除误标' if tag['enabled'] else '恢复标签'}}</button>
 </form>
 % end
 </details>
 % for media in work['media']:
 <a href="{{media['link']}}" rel="noreferrer">在 Emby 中打开</a>
 % end
 </div></article>
 % end
 % if not items:
 <p>当前没有符合条件的作品。可检查待确认、片库同步和训练状态。</p>
 % end
 % if page > 1:
 <a href="/v2?entry={{entry}}&page={{page-1}}">上一页</a>
 % end
 <a href="/v2?entry={{entry}}&page={{page+1}}">下一页</a>
</div>
