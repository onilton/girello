#!/usr/bin/python
# -*- coding: utf-8 -*-

from github3 import login
from configobj import ConfigObj
from trello import TrelloClient
from collections import namedtuple
import pprint

pp = pprint.PrettyPrinter(indent=4)
users_cache = {}

GithubConfig = namedtuple('GithubConfig', ['token', 'identifier'])
TrelloConfig = namedtuple(
    'TrelloConfig',
    ['api_key', 'api_secret', 'token', 'token_secret'],
)


class GirelloTrello:
    def __init__(self, boards, config, github_users):
        # TO-DO: implement a warning when a board in config_boards does not
        # exist in boards

        self.boards = []

        # print "GirelloTrello config_boards"
        # pp.pprint(config.boards)
        for board in boards:
            # print "GirelloTrello dname="+board.name
            if board.name in config.boards:
                board_config = config.boards[board.name]

                gi_board = GirelloBoard(
                    board,
                    config,
                    github_users,
                    doing_list_name=board_config.get('doing_list'),
                    review_list_name=board_config.get('review_list'),
                    repositories=board_config.get('repositories', list()),
                    exclude_repositories=board_config.get(
                        'exclude_repositories',
                        list()
                    ),
                )

                self.boards.append(gi_board)

        self.repos = {}
        for board in self.boards:
            for repo in board.repositories:
                self.repos[repo] = board

    def get_boards_for_repo(self, repo):
        boards_for_repo = set()

        if repo in self.repos:
            boards_for_repo.add(self.repos[repo])

        for board in self.boards:
            if ((board.repositories is None or
                    not board.repositories) and
                    repo not in board.exclude_repositories):
                # If board has no repositories set and
                # if repo not in exclude list we should return it
                # for this repo
                boards_for_repo.add(board)

        return boards_for_repo


class GirelloBranch:
    def __init__(self, repo, name):
        self.repo = repo
        self.name = name
        self.card_tag = "["+self.repo[1]+"/"+self.name+"]"


class UsersMapper:
    def __init__(self, trello_users, github_users, config):
        self.usernames_map = config.usernames_map

        self.trello_users = {}
        for user in trello_users:
            self.trello_users[user.username] = user

        self.github_users = {}
        for user in github_users:
            self.github_users[user.login] = user

    def get_trello_user(self, github_login):
        trello_username = self.usernames_map.get(github_login, github_login)

        if trello_username in self.trello_users:
            return self.trello_users[trello_username]
        return None


class GirelloBoard:
    def __init__(self,
                 board,
                 config,
                 github_users,
                 doing_list_name=None,
                 review_list_name=None,
                 repositories=None,
                 exclude_repositories=None):

        self.info = board
        self.members = board.all_members()
        self.users_mapper = UsersMapper(self.members, github_users, config)
        self.open_lists = board.open_lists()
        self.doing_list = None
        self.review_list = None
        self.done_list = None
        self.lists_before_doing = []

        self.repositories = repositories
        self.exclude_repositories = exclude_repositories

        for l in self.open_lists:
            if self.review_list is not None and self.done_list is None:
                self.done_list = l

            if l.name == doing_list_name:
                self.doing_list = l

            if self.doing_list is None:
                self.lists_before_doing.append(l)

            if l.name == review_list_name:
                self.review_list = l

    def find_open_card(self, card_name):
        for c in self.info.open_cards():
            if c.name == card_name:
                return c
        return None

    def find_open_card_by_substr(self, card_name_substr):
        for c in self.info.open_cards():
            if c.name.find(card_name_substr) != -1:  # substring
                return c
        return None

    def find_list(self, list_name):
        for l in self.open_lists:
            for c in l.list_cards():
                if l.name == list_name:
                    return c
        return None


class ConfigSession:
    def __init__(self, config, session_name):
        self.session = config[session_name]

    def get(self, option, default=None):
        if default is not None:
            return self.session.get(option, default)
        else:
            return self.session.get(option)

    def getint(self, option, default=None):
        if default is not None:
            return int(self.session.get(option, str(default)))
        else:
            return int(self.session.get(option))


class GirelloConfig:
    def __init__(self, filename='settings.cfg'):
        self.config = ConfigObj(filename)

        github_section = ConfigSession(self.config, 'Github')
        self.github = GithubConfig(
            token=github_section.get('token'),
            identifier=github_section.get('identifier'),
        )

        trello_section = ConfigSession(self.config, 'Trello')
        self.trello = TrelloConfig(
            api_key=trello_section.get('api_key'),
            api_secret=trello_section.get('api_secret'),
            token=trello_section.get('oauth_token'),
            token_secret=trello_section.get('oauth_token_secret'),
        )

        girello_section = ConfigSession(self.config, 'Girello')

        temp_allowed_orgs = girello_section.get('allowed_orgs')
        if isinstance(temp_allowed_orgs, basestring):
            allowed_orgs_list = list(temp_allowed_orgs)
        else:
            allowed_orgs_list = temp_allowed_orgs

        self.allowed_orgs = set(allowed_orgs_list)

        # We ignore board session names
        raw_boards = girello_section.get('boards', dict()).values()
        self.boards = dict((b['name'], b) for b in raw_boards)

        # We ignore username session names
        raw_usernames_map = girello_section.get(
            'usernames',
            dict()
        ).values()

        self.usernames_map = dict((u['github'], u['trello'])
                                  for u in raw_usernames_map)


class CommitEvent:
    def __init__(self, **entries):
        self.__dict__.update(entries)

        self.browser_url = self.url.replace(
            'https://api.github.com/repos/',
            'https://github.com/'
        ).replace(
            '/commits/',
            '/commit/',
        )


class PushEvent:
    def __init__(self, **entries):
        self.__dict__.update(entries)

        commitsObjects = []
        for commit in self.commits:
            commitsObjects.append(CommitEvent(**commit))

        self.commits = commitsObjects

        # removes prefix refs/heads/ from ref
        self.branch_name = '/'.join(self.ref.split('/')[2:])

    def sync_with_boards(self, parent_event, girello_trello):
        affected_boards = girello_trello.get_boards_for_repo(
            parent_event.repo[1]
        )

        # the branch
        branch = GirelloBranch(parent_event.repo, self.branch_name)

        for board in affected_boards:
            card = board.find_open_card_by_substr(branch.card_tag)
            if card is not None:
                # If the card have no name, only the tag
                if card.name == branch.card_tag:
                    # First commit becomes the card name
                    card.name += ' ' + self.commits[0].message
                    card._set_remote_attribute('name', card.name)

                # Build list of commits string
                commit_list_str = ''
                for commit in self.commits:
                    commit_list_str += (
                        '\n**[{short_sha}]({browser_url})** - {message}'
                    ).format(
                        short_sha=commit.sha[0:7],
                        browser_url=commit.browser_url,
                        message=commit.message
                    )

                # TODO: check description size:
                # Max description size is 16385
                # Append commits list to description
                card.set_description(
                    card.description + commit_list_str
                )

                trello_user = board.users_mapper.get_trello_user(
                    parent_event.actor.login
                )

                if trello_user is not None:
                    # Fix error in py-trello
                    if (hasattr(card, 'idMembers') and
                            (not hasattr(card, 'members_ids'))):
                        setattr(card, 'member_ids', card.idMembers)
                    else:
                        setattr(card, 'member_ids', list())

                    # If user is not already in card members
                    # add it
                    if trello_user.id not in card.member_ids:
                        card.assign(trello_user.id)
                        card.member_ids.append(trello_user.id)


class PullRequestEvent:
    def __init__(self, **entries):
        self.__dict__.update(entries)

        # the branch (of the pull request)
        branch_name = self.pull_request.head.ref
        repo = self.pull_request.head.repo
        self.branch_to_merge = GirelloBranch(repo, branch_name)

    def sync_with_boards(self, parent_event, girello_trello):
        affected_boards = girello_trello.get_boards_for_repo(
            parent_event.repo[1]
        )

        # new pull request
        if self.action == 'opened':
            for board in affected_boards:
                card = board.find_open_card_by_substr(self.branch_to_merge.card_tag)
                if card is not None:
                    # card found, move to review list
                    card.change_list(board.review_list.id)

        # closed pull request
        if self.action == 'closed':
            for board in affected_boards:
                card = board.find_open_card_by_substr(self.branch_to_merge.card_tag)
                if card is not None:
                    # card found, move to done list
                    card.change_list(board.done_list.id)


class CreateBranchEvent:
    def __init__(self, **entries):
        self.__dict__.update(entries)

    def sync_with_boards(self, parent_event, girello_trello):
        affected_boards = girello_trello.get_boards_for_repo(
            parent_event.repo[1]
        )

        # the new branch
        branch = GirelloBranch(parent_event.repo, self.ref)

        for board in affected_boards:
            card = board.find_open_card_by_substr(branch.card_tag)
            if card is not None:
                # card found, move to doing list
                card.change_list(board.doing_list.id)
            else:
                # card not found, create one in doing list
                board.doing_list.add_card(branch.card_tag)


class EventFactory:
    def create_event(self, gh_event):
        if event.type == 'PushEvent':
            return PushEvent(**(gh_event.payload))

        if event.type == 'PullRequestEvent':
            return PullRequestEvent(**(gh_event.payload))

        if (event.type == 'CreateEvent' and
                event.payload['ref_type'] == 'branch'):
            return CreateBranchEvent(**(gh_event.payload))

        return None


config = GirelloConfig()
gh = login(token=config.github.token)
trello = TrelloClient(
    api_key=config.trello.api_key,
    api_secret=config.trello.api_secret,
    token=config.trello.token,
    token_secret=config.trello.token_secret,
)

#auth = gh.authorization(config.github.identifier)
#print pp.pprint(gh.rate_limit())
user = gh.user()
orgs = [org for org in gh.iter_orgs() if org.login in config.allowed_orgs]


github_members = set()
for org in orgs:
    for member in org.iter_members():
        github_members.add(member)

girello_trello = GirelloTrello(trello.list_boards(), config, github_members)

event_factory = EventFactory()

for org in orgs:
    print "org.login=" + org.login
    print "org.name=" + org.name
    print "org.members:" + org.login
    #events = user.iter_org_events(org.name)
    events = user.iter_org_events(org.login, 10)
    for event in reversed(list(events)):
        print "event_id="+event.id
        print "event_type="+event.type
        if event.type == 'PushEvent':
            push_event = event_factory.create_event(event)
            #print push_event.ref
            print "branch="+push_event.branch_name
            print "num_of_commits=" + str(push_event.size)
            #print repr(push_event)
            #print repr(push_event.commits[0])
            print "browser_url="+push_event.commits[0].browser_url
            pp.pprint(push_event.commits[0].__dict__)
            push_event.sync_with_boards(event, girello_trello)

        if event.type == 'PullRequestEvent':
            #print "PULL="+repr(event.payload['pull_request'].__dict__['head'].__dict__)
            #pp.pprint(event.payload['pull_request'].__dict__['head'].__dict__)
            pull_request_event = event_factory.create_event(event)
            print "branch_to_merge=" + pull_request_event.branch_to_merge.card_tag
            print "action=" + pull_request_event.action
            pull_request_event.sync_with_boards(event, girello_trello)

        if (event.type == 'CreateEvent' and
                event.payload['ref_type'] == 'branch'):
            create_branch_event = event_factory.create_event(event)
            print "branch_ref=" + create_branch_event.ref
            print "master_branch=" + create_branch_event.master_branch
            print "event_repo="+str(event.repo)

            create_branch_event.sync_with_boards(event, girello_trello)

        print "event_actor="+event.actor.login
        #event.actor.refresh()
        #print "event_actor_name="+event.actor.name
        print "event_created_At="+str(event.created_at)
        print "event_repo="+str(event.repo)
        #if event.payload.__dict__ is not None:
            #vars(event.payload)

        #print event.to_json()
        print ""

print "girello_trello"
for b in girello_trello.boards:
    print "b.id=" + b.info.id
    print "b.name=" + b.info.name
