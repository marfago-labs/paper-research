Feature: A plugin that installs cleanly and keeps its promises
  As someone about to install this plugin
  I want its structure and its security promises to be checked on every change
  So that what the README says is what I get

  Background:
    Given the plugin repository

  Scenario: Every skill is well formed
    Then every skill has a SKILL.md whose name is its folder name
    And every skill description says when to use it and fits in 1024 characters
    And no skill refers to the old workspace layout

  Scenario: Skills only refer to scripts that exist
    Then every script a skill refers to exists

  Scenario: The manifests are valid
    Then the manifests are valid and agree on the plugin name

  Scenario: The rules that init writes cover every skill
    Then the rules written by init name every skill

  Scenario: The rules send every paper that is read through the read skill
    Then the rules written by init route paper reading through the read skill
    And the arxiv skill routes reading a paper through the read skill
    And the init skill loads the new rules into the session that ran it

  Scenario: Questions about what the user has are answered from the graph too
    Then the rules written by init send questions about existing notes to the graph

  Scenario: Claude never writes its own permissions
    Then the init skill has the user run the write step
    And the troubleshooting page explains the auto mode block

  Scenario: No outside code is needed to run it
    Then the scripts import only the Python standard library

  Scenario: Scripts only talk to the hosts the README promises
    Then the scripts name only these hosts: arxiv.org, export.arxiv.org, www.arxiv.org, api.semanticscholar.org, www.semanticscholar.org, huggingface.co, doi.org, dx.doi.org, www.w3.org, purl.org, a9.com

  Scenario: The recap page works offline
    Then the page loads only files shipped next to it

  Scenario: The documentation points only to things that exist
    Then every link in the docs points to a file and heading that exist

  Scenario: The documentation covers every skill
    Then the docs describe every skill

  Scenario: The command reference covers every command
    Then the command reference lists every command of graph
    And the command reference lists every command of arxiv
    And the command reference lists every command of scholar
    And the command reference lists every option of init
