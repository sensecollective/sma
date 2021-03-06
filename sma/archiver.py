import os, re, sys

import facebook
import requests

from sma import files 
from sma import sponge
from sma import utils
from sma.clusterer import Clusterer
from sma.config import DIR_BASE

# utility for handling facebook's paginated responses
def handle_paginated_response(json, func):
	data = json['data'] if 'data' in json else []
	next = json['paging']['next'] if 'paging' in json and 'next' in json['paging'] else None
	func(data)
	if next:
		return requests.get(next).json()
	return None

class Archive(object):
	def __init__(self, *args, **kwargs):
		self.id = None

	def extract_links(self, s, description_override=None):
		urls = utils.extract_urls(s)
		description = s if not description_override else description_override
		for u in urls:
			if not u in self.links:
				self.links[u] = Link(u, description=description)

	def save(self, filename, obj):
		files.save_obj(obj, self.id, filename)

	def file_load(self, filename):
		return files.load_obj(self.id, filename)

	# builds snapshots of links
	def snaps(self, force=False):
		for url in self.links:
			self.links[url].screenshot(force=force)
			self.links[url].summarize(force=force)
			self.links[url].archive(force=force)

	# Generates markdown for archive and saves it to a location
	def save_markdown(self, md, save_location=None):
		files.save_txt(md, subdir=self.id, save_location=save_location)


class GroupArchive(Archive):
	def __init__(self, graph, id, *args, **kwargs):
		super(GroupArchive, self).__init__(args, kwargs)
		self.graph = graph
		self.id = id
		self.obj = None
		self.users = {}
		self.links = {}
		self.posts = {}
		self.isLoaded = False
		filename = kwargs['filename'] if 'filename' in kwargs else 'archive.pkl'
		print "Initiating group archive: ",id
		self.file_load(filename)
		if not self.obj and self.graph:
			self.graph_load()
		print "Loaded %s posts" % len(self.posts)
		print "..having a total of %s comments" % sum(len(self.posts[k].comments) for k in self.posts)
		print "..containing %s links" % len(self.links)
		print "..with %s participants" % len(self.users)

	def print_links(self):
		for k in self.links:
			print self.links[k]
			print

	def file_load(self, filename='archive.pkl'):
		d = super(GroupArchive, self).file_load(filename)
		if not d:
			return False
		if 'obj' in d:
			self.obj = d['obj']
			self.ingest_obj()
		if 'links' in d:
			for l in d['links']:
				self.links[l.url] = l
		if 'posts' in d:
			for p in d['posts']:
				post = PostArchive(self.graph, None, obj=p)
				for k in post.links:
					if k in self.links:
						post.links[k] = self.links[k]
				self.add_post(post)
		self.isLoaded = True
	
	def save(self, filename='archive.pkl'):
		d = {'obj':self.obj, 'posts': [], 'links':[]}
		for k in self.posts:
			d['posts'].append(self.posts[k].obj)
		for k in self.links:
			d['links'].append(self.links[k])
		super(GroupArchive, self).save(filename, d)

	def graph_load(self):
		print "Loading from Facebook"
		try:
			self.obj = self.graph.get_object(id=self.id)
		except:
			print "** Failed!"
			self.obj = {}
			return
		self.ingest_obj()
		self.graph_load_posts()
		self.save()
		self.isLoaded = True

	def graph_load_posts(self):
		def load_data(data):
			for d in data:
				p = PostArchive(self.graph, d['id'])
				self.add_post(p)
		# Go!
		content = self.graph.get_connections(self.id, 'feed')
		while content:
			content = handle_paginated_response(content, load_data)
	
	def ingest_obj(self):
		self.name = self.obj['name']
		self.initiator = User(self.obj['owner'])
		self.users[self.initiator.id] = self.initiator
		self.description = self.obj['description'] if 'description' in self.obj else ""
		self.email = self.obj['email'] if 'email' in self.obj else ""
		self.extract_links(self.description)
		print "Ingested group: ", self.name
		

	def add_post(self, post):
		if not post.id in self.posts:
			self.posts[post.id] = post
			for k in post.links:
				if not k in self.links:
					self.links[k] = post.links[k]
			for k in post.users:
				if not k in self.users:
					self.users[k] = post.users[k]
			#print str(post)

	# builds snapshots of links
	def snaps(self):
		count = 0
		for url in self.links:
			if count % 5 == 4:
				self.save()
			self.links[url].screenshot()
			self.links[url].summarize()
			self.links[url].archive()
			count += 1

	# Generates markdown for archive (and all posts!) and saves it to a location
	def markdownify(self):
		# markdownify links in text
		def mdl(text):
			urls = utils.extract_urls(text)
			for u in urls:
				if u in self.links:
					text = text.replace(u, self.links[u].markdownify(summary=True))
			return text
		# make path for posts
		path = os.path.join(DIR_BASE, self.id, 'posts')
		if not os.path.exists(path):
			os.makedirs(path)
		# begin generating output
		output = "%s\n%s\n\n%s\n" % (self.name, "="*len(self.name), mdl(self.description))
		output = "%s\n\n" % output
		output = "%sReferences\n----------\n" % output
		# show all links
		c = Clusterer()
		clinks = c.cluster_links(self.links)
		for i in clinks:
			output = "%s### Group %s\n" % (output, i)
			for l in clinks[i]:
				output = "%s\n%s" % (output, l.markdownify(summary=True, prefer_snapshot=True))
		#for k in self.links:
		#	output = "%s\n%s" % (output, self.links[k].markdownify(summary=True, prefer_snapshot=True))
		output = "%s\n\n" % output
		output = "%sPosts\n-----\n" % output
		# show all posts
		back_link = "[< back to %s](%s)" % (self.name, "/group/"+self.id)
		for k in self.posts:
			self.posts[k].markdownify(save_location=os.path.join(path, "%s.md" % k), back_link=back_link)
			output = "%s* [%s](%s)\n" % (output, self.posts[k].get_shorty(), "/group/%s/post/%s" %(self.id, k))
		output = "%s\n\n" % output
		output = "%sContributors\n------------\n" % output
		# show all posts
		for k in self.users:
			output = "%s* %s\n" % (output, self.users[k].name)
		# save
		self.save_markdown(output)
		files.save_txt(self.name, subdir=self.id, filename="title.txt")
		
class PostArchive(Archive):
	def __init__(self, graph, id, *args, **kwargs):
		super(PostArchive, self).__init__(args, kwargs)
		self.graph = graph
		self.id = id
		self.obj = None
		self.users = {}
		self.links = {}
		self.comments = []
		if 'obj' in kwargs:
			self.obj = kwargs['obj']
			self.ingest_obj()
		if not self.obj:
			print "Initiating post archive: ",id
			filename = kwargs['filename'] if 'filename' in kwargs else 'archive.pkl'
			self.file_load(filename)
			if self.graph and not self.obj:
				self.graph_load()

	def get_shorty(self, truncate=80):
		if self.message:
			return re.sub('[\[\]\n\r]', ' ', self.message[:truncate])
		elif 'story' in self.obj:
			return self.obj['story'][:truncate]
		elif self.link and hasattr(self.link, 'url'):
			return self.link.url
		else:
			return "Untitled post"

	def file_load(self, filename='archive.pkl'):
		d = super(PostArchive, self).file_load(filename)
		if not d:
			return False		
		if 'obj' in d:
			self.obj = d['obj']
			self.ingest_obj()

	def save(self, filename='archive.pkl'):
		d = {'obj':self.obj}
		super(PostArchive, self).save(filename, d)

	def graph_load(self):
		print "Loading from Facebook"
		self.obj = self.graph.get_object(id=self.id)
		self.ingest_obj()

	def ingest_obj(self):
		self.id = self.obj['id']
		self.initiator = User(self.obj['from'])
		self.users[self.initiator.id] = self.initiator
		self.message = self.obj['message'] if 'message' in self.obj else ""
		self.link = self.obj['link'] if 'link' in self.obj else ""
		self.ingest_comments()
		self.extract_links(self.message)
		self.extract_links(self.link, description_override=self.message)
		#print "Ingested post initiated by ",self.initiator.name

	def ingest_comments(self):
		if 'comments' in self.obj and 'data' in self.obj['comments']:
			for c in self.obj['comments']['data']:
				comment = Comment(c)
				if not comment.user.id in self.users:
					self.users[comment.user.id] = comment.user
				self.comments.append(comment)
				self.extract_links(comment.message)

	def add_user(self, user_json):
		u = User(user_json)
		self.users[u.id] = u

	def __str__(self):
		return "Post initiated by %s\nThere are %s comments and %s links\n%s people participated" % (self.initiator.name.encode('utf-8').strip(), len(self.comments),len(self.links), len(self.users))

	def raw_text(self):
		content = self.message
		for c in self.comments:
			content = "%s %s" % (content, c.message)
		return content

	# Generates markdown for archive and saves it to a location
	def markdownify(self, save_location=None, back_link=None):
		# markdownify links in text
		def mdl(text):
			urls = utils.extract_urls(text)
			for u in urls:
				if u in self.links:
					text = text.replace(u, self.links[u].markdownify(summary=True))
			return text
		# make markdown
		output = ""
		if back_link:
			output = "%s\n\n" % back_link
		output = "%s_%s:_\n" % (output, self.initiator.name)
		initial_message = self.message
		initial_lines = initial_message.split('\n')
		for l in initial_lines:
			output = "%s### %s\n" % (output, l)
		ouput = "%s---\n" % output
		if self.link and self.link in self.links:
			output = "%s%s\n" % (output, self.links[self.link].markdownify(summary=True))
		urls = utils.extract_urls(initial_message)
		for u in urls:
			if not u==self.link and u in self.links:
				output = "%s%s\n" % (output, self.links[u].markdownify(summary=True))
		output = "%s\n" % output
		for c in self.comments:
			output = "%s**%s:**\n%s\n\n" % (output, c.user.name, mdl(c.message))
		self.save_markdown(output, save_location=save_location) 
		#
		users_str = ' - '.join([self.users[k].name for k in self.users])
		if not save_location:
			title = initial_message if initial_message else self.link if hasattr(self, 'link') and self.link else 'no title available'
			title = utils.truncate(re.sub('[\r\n]', ' / ', title), 180)
			files.save_txt(title, subdir=self.id, filename="title.txt")

# Represents a user
class User(object):
	def __init__(self, json):
		self.id = json['id']
		self.name = json['name']
		self.count = 1

	def increment(self):
		self.count += 1

# Represents a comment
class Comment(object):
	def __init__(self, json):
		self.obj = json
		self.user = User(json['from'])
		self.message = json['message']

# Represents a link
class Link(object):
	def __init__(self, url, *args, **kwargs):
		self.url = url
		self.description = kwargs['description'] if 'description' in kwargs else ""
		self.description = self.description.replace(self.url,"")
		self.title = ""
		self.summary = ""
		self.archived_text = ""
		self.snapshot = None
		self.image = None

	def __str__(self):
		return "URL: %s\nDescription: %s" % (self.url.encode('utf-8').strip(), self.description.encode('utf-8').strip())

	# @todo: ingest content (beautifulsoup? in the future, should it download video?)
	def archive(self, force=False):
		sponge.content(self.url, force=force)

	# returns a markdown string representation of itself
	# summary=True puts title, summary and image into a blockquote
	def markdownify(self, summary=False, text_only=False, prefer_snapshot=False):
		def absurl(path):
			return files.tnurl(path)
		title_to_use = self.title if hasattr(self,'title') and self.title else self.url
		title_to_use_bracket_safe = re.sub('[\[\]\(\)]', '', title_to_use)
		title_to_use_quote_safe = re.sub('["\(\)]', '', title_to_use)
		preferred_image = self.snapshot if prefer_snapshot or not summary else self.image
		# youtube links shouldshow thumbnail, not screenshot if possible
		if utils.is_youtube(self.url):
			preferred_image = self.image
		if not preferred_image:
			if self.image:
				preferred_image = self.image
			if self.snapshot:
				preferred_image = self.snapshot
		if summary:
			output = "<!-- r -->\n" 
			if not text_only:
				if preferred_image:
					output = "%s> [ ![%s](%s \"%s\") ](%s \"%s\") <br />\n" % (output, title_to_use_bracket_safe, absurl(preferred_image), title_to_use_quote_safe, files.lurl(self.url), title_to_use_quote_safe)
			output = "%s> [%s](%s \"%s\") <br />\n" % (output, title_to_use_bracket_safe, files.lurl(self.url), title_to_use_quote_safe)
			if self.summary:
				about = "%s... %s" % (self.summary, self.description)
				about = re.sub('http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', '', about)
				about = re.sub(r'[\r\n]*', '', about)
				output = "%s> %s<br/>\n" % (output, about[:500])
			return output
		else:
			if not text_only:
				#[ ![Image](/images/image.jpg "Image title") ](http://google.com "Google")
				if preferred_image:
					return "[ ![%s](%s \"%s\") ](%s \"%s\")" % (title_to_use_bracket_safe, absurl(preferred_image), title_to_use_quote_safe, files.lurl(self.url), title_to_use_quote_safe)
			# fallback to text only
			return "[%s](%s \"%s\")" % (title_to_use_bracket_safe, files.lurl(self.url), title_to_use_quote_safe)
		# fallback
		return ""

	def raw_text(self, include_content=False):
		if include_content:
			return "%s %s %s %s" % (self.title if hasattr(self,'title') else "", self.description, self.summary, files.readable(self.url).decode('utf-8', 'ignore'))
		else:
			return "%s %s %s" % (self.title if hasattr(self,'title') else "", self.description, self.summary)

	def summarize(self, force=False):
		if force or not self.title:
			try:
				self.title, self.summary, image_url = sponge.summary(self.url)
			except:
				image_url = None
				print "Failed extraction of ", self.url
			if image_url and (force or not self.image):
				self.image = sponge.image(image_url)
		# try and make thumbnail
		files.thumbnail(self.image)

	# thumbnail
	def screenshot(self, force=False):
		self.snapshot = sponge.screenshot(self.url, force=force)

class FB(object):
	def __init__(self, access_token):
		self.access_token = access_token
		self.g = facebook.GraphAPI(access_token)
		self.name = "Me"
		self.groups = []
		self.posts = []

	def archive_group(self, id):
		a = GroupArchive(self.g, id)
		a.save()
		a.markdownify()

	def rebuild_group(self, id, do_snaps=False):
		a = GroupArchive(self.g, id)
		if do_snaps:
			a.snaps()
		a.markdownify()
		a.save()

	def load_groups(self):
		me = self.g.get_object('me')
		self.name = me['name']
		#groups = g.get_connections('me', 'feed')
		def load_data(data):
			for g in data:
				self.groups.append((g['id'], g['name']))
		# Go!
		content = self.g.get_connections('me', 'groups')
		while content:
			content = handle_paginated_response(content, load_data)

	def archive_post(self, id):
		a = PostArchive(self.g, id)
		a.save()
		a.snaps()
		a.markdownify()
		a.save()

	def load_posts(self, min_comments=25):
		me = self.g.get_object('me')
		self.name = me['name']
		def load_data(data):
			for d in data:
				if 'comments' in d and 'data' in d['comments'] and len(d['comments']['data'])>=min_comments:
					try:
						title = d['message'][:100] if 'message' in d else d['name'] if 'name' in d else d['story']
					except:
						title = "A post with %s comments" % len(d['comments']['data'])
					self.posts.append((d['id'], title))
		# Go!
		content = self.g.get_connections('me', 'feed')
		while content:
			content = handle_paginated_response(content, load_data)
		# and stream
		"""
		content = self.g.get_connections('me', 'home')
		count = 0
		while content and count<20:
			count += 1
			content = handle_paginated_response(content, load_data)
		"""
			

	def markdownify(self):
		output = "%s\n%s\n\n" %(self.name, '='*len(self.name))
		output = "%s### Groups (click one to archive, then wait a couple minutes)\n" % output
		for g in self.groups:
			output = "%s- %s\n" % (output, "[%s](/fb/archive_group/%s)" %(g[1],g[0]))
		output = "%s### Posts (click one to archive, then wait a couple minutes)\n" % output
		for g in self.posts:
			t = re.sub('[\[\]\(\)\n]', '', g[1])
			output = "%s- %s\n" % (output, "[%s](/fb/archive_post/%s)" %(t,g[0]))
		return output

if __name__ == '__main__':
	args = sys.argv[1:]
	g = GroupArchive(None, args[1])
	if g.isLoaded:
		if args[2]=='markdownify':
			g.markdownify()
		elif args[2]=='build':
			g.snaps()
			g.markdownify()
			g.save()

