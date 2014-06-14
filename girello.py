#!/usr/bin/python
# -*- coding: utf-8 -*-

from github3 import login
from configobj import ConfigObj
from collections import namedtuple
import pprint

pp = pprint.PrettyPrinter(indent=4)
users_cache = {}

GithubConfig = namedtuple('GithubConfig', ['token', 'identifier'])


class ConfigSession:
    def __init__(self, config, session_name):
        self.session = config[session_name]

    def get(self, option):
        return self.session.get(option)

    def getint(self, option):
        return int(self.session.get(option))


class GirelloConfig:
    def __init__(self, filename='settings.cfg'):
        self.config = ConfigObj(filename)

        github_section = ConfigSession(self.config, 'Github')
        self.github = GithubConfig(
            token=github_section.get('token'),
            identifier=github_section.get('identifier'),
        )

        girello_section = ConfigSession(self.config, 'Girello')
        self.allowed_orgs = set(
            girello_section.get('allowed_orgs').split(',')
        )


class CommitEvent:
    def __init__(self, **entries):
        self.__dict__.update(entries)


class PushEvent:
    def __init__(self, **entries):
        self.__dict__.update(entries)

        commitsObjects = []
        for commit in self.commits:
            commitsObjects.append(CommitEvent(**commit))

        self.commits = commitsObjects

        self.branch = self.ref.split('/')[-1]


class PullRequestEvent:
    def __init__(self, **entries):
        self.__dict__.update(entries)
        self.branch_to_merge = self.pull_request.head.ref


class CreateBranchEvent:
    def __init__(self, **entries):
        self.__dict__.update(entries)


config = GirelloConfig()
gh = login(token=config.github.token)
#auth = gh.authorization(config.github.identifier)
#print pp.pprint(gh.rate_limit())
user = gh.user()
orgs = [org for org in gh.iter_orgs() if org.login in config.allowed_orgs]

for org in orgs:
    print "org.login=" + org.login
    print "org.name=" + org.name
    print "org.members:" + org.login
    #events = user.iter_org_events(org.name)
    events = user.iter_org_events(org.login, 10)
    for event in events:
        print "event_id="+event.id
        print "event_type="+event.type
        if event.type == 'PushEvent':
            push_event = PushEvent(**(event.payload))
            #print push_event.ref
            #print push_event.size
            print "branch="+push_event.branch
            #print repr(push_event)
            #print repr(push_event.commits[0])
            pp.pprint(push_event.commits[0].__dict__)
        if event.type == 'PullRequestEvent':
            #print "PULL="+repr(event.payload['pull_request'].__dict__['head'].__dict__)
            #pp.pprint(event.payload['pull_request'].__dict__['head'].__dict__)
            pull_request_event = PullRequestEvent(**event.payload)
            print "branch_to_merge=" + pull_request_event.branch_to_merge
            print "action=" + pull_request_event.action

        if (event.type == 'CreateEvent' and
                event.payload['ref_type'] == 'branch'):
            create_branch_event = CreateBranchEvent(**event.payload)
            print "branch_ref=" + create_branch_event.ref
            print "master_branch=" + create_branch_event.master_branch

        print "event_actor="+event.actor.login
        #event.actor.refresh()
        #print "event_actor_name="+event.actor.name
        print "event_created_At="+str(event.created_at)
        print "event_repo="+str(event.repo)
        #if event.payload.__dict__ is not None:
            #vars(event.payload)

        #print event.to_json()
        print ""

