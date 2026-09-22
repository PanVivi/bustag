% rebase('base.tpl', title='偏好与身份确认', path=path)
<div class="container">
<a href="/v2">返回推荐</a>
<h5>作品人工反馈（可更正已排除的作品）</h5>
% for work in feedback:
<form method="post" action="/v2/feedback/{{work['work_id']}}">
<input type="hidden" name="csrf" value="{{csrf}}">
{{work['code'] or work['title']}} · {{'喜欢' if work['value'] else '不喜欢'}}
<button name="value" value="1">喜欢</button><button name="value" value="0">不喜欢</button></form>
% end
<h5>演员人工三态</h5>
% for actor in actors:
<form method="post" action="/v2/actor/{{actor['actor_id']}}">
<input type="hidden" name="csrf" value="{{csrf}}">
{{actor['name']}} · {{actor['actor_id']}}
<select name="state">
% for value,label in [('like','喜欢'),('dislike','不喜欢'),('pending','待确认')]:
<option value="{{value}}" {{'selected' if actor['state']==value else ''}}>{{label}}</option>
% end
</select><button>保存</button></form>
% end
<details><summary>经人工核实，合并同一人的网站身份</summary>
<form method="post" action="/v2/merge-actor"><input type="hidden" name="csrf" value="{{csrf}}">
<label>原演员 ID <input name="source_actor" required></label>
<label>目标演员 ID <input name="target_actor" required></label><button>确认同一演员</button></form>
<p>仅相同姓名不足以合并。有矛盾人工偏好时需先由用户处理。</p></details>
<h5>标签来源与语义映射</h5>
% for tag in tags:
<form method="post" action="/v2/map-tag">
<input type="hidden" name="csrf" value="{{csrf}}">
% for key in ['source','category','source_id']:
<input type="hidden" name="{{key}}" value="{{tag[key]}}">
% end
<p>{{tag['source']}} / {{tag['category']}} / {{tag['name']}} → {{tag['canonical_category']}} / {{tag['canonical_name']}} · {{'人工核实' if tag['verified'] else '未核实'}}</p>
<label>规范标签 ID <input name="tag_id" value="{{tag['tag_id']}}" required></label><button>确认语义映射</button>
</form>
% end
<h5>待确认媒体副本</h5>
% for media in pending:
<form method="post" action="/v2/resolve-media"><input type="hidden" name="csrf" value="{{csrf}}">
% for key in ['server','item_id']:
<input type="hidden" name="{{key}}" value="{{media[key]}}">
% end
{{media['item_id']}} <label>确认作品 ID <input name="work_id" required></label><button>确认对应作品</button></form>
% end
<p>作品 ID 可在推荐卡片查看。确认前请在私有 Emby 核对，页面不公开 NAS 路径。</p>
% if page > 1:
<a href="/v2/manage?page={{page-1}}">上一页</a>
% end
<a href="/v2/manage?page={{page+1}}">下一页</a>
</div>
