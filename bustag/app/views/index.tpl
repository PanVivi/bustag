% rebase('base.tpl', title='推荐', path=path, msg=msg)
% curr_page = page_info[2]

<div class="container">
% if filter_value:
 <div class="alert alert-info py-2">
  当前筛选：{{filter_label}} · {{filter_value}}
  <a class="float-right" href="{{clear_url}}">清除筛选</a>
 </div>
% end
 <div class="row py-3">
	<div class="col-12">
		<ul class="nav nav-tabs">
		<li class="nav-item">
			<a class="nav-link {{'active' if like==1 else ''}}" href="?like=1">喜欢</a>
		</li>
		<li class="nav-item">
			<a class="nav-link {{'' if like==1 else 'active'}}" href="?like=0">不喜欢</a>
		</li>
		<li class="nav-item">
		</li>
		</ul>
	</div>
</div>
%#generate list of rows of items
% i = 1
%for item in items:
<form id="form-{{i}}" action="/correct/{{item.fanhao}}{{query_url(curr_page)}}" method="post">
	<div class="row py-3">
		<div class="col-12 col-md-4">
		<img class="img-fluid img-thumbnail coverimg" src="{{poster_src(item.cover_img_url)}}">
		</div>

			<div class="col-7 col-md-5">
			<div class="small text-muted">id: {{item.id}}</div>
			<div class="small text-muted">发行日期: {{item.release_date}}</div>
			<div class="small text-muted">添加日期: {{item.add_date}}</div>
			% if getattr(item, 'recommend_score', None) is not None:
			<div class="small"><span class="badge badge-success">推荐分数 {{int(round(item.recommend_score * 100))}}</span></div>
			% end
			<h6>{{item.fanhao}} </h6>
			<a href="{{item.url}}" target="_blank"> {{item.title[:30]}} </a>
			<div>
			% for t in item.tags_dict['genre']:
				<a class="badge badge-primary" href="{{tag_url('genre', t)}}">{{t}}</a>
			% end
			</div>
			<div>
			% for t in item.tags_dict['star']:
				<a class="badge badge-warning" href="{{tag_url('star', t)}}">{{t}}</a>
			% end
			</div>

			</div>
		<div class="col-5 col-md-3  align-self-center">
		<input type=hidden name="formid" value="form-{{i}}">
		<button type="submit" name="submit" class="btn btn-primary mx-2" value="1">正确</button>
		<button type="submit" name="submit" class="btn btn-danger" value="0">错误</button>
		</div>
	</div>
	</form>
% i = i + 1
%end
% include('pagination.tpl', page_info=page_info)

</div>
