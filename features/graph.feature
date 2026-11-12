Feature: A knowledge graph that stays trustworthy as it grows
  As a reader who adds papers every day
  I want the graph to catch duplicates and refuse bad edits
  So that the connections between papers can be relied on

  Background:
    Given an empty graph

  Scenario: Adding an entity
    When I run graph add --type dataset --name "Terminal-Bench 2.1" --alias TB-2.1 --url https://arxiv.org/abs/2601.11868
    Then the command succeeds
    And the output mentions "added dataset:terminal-bench-2-1"
    And the entity "dataset:terminal-bench-2-1" is named "Terminal-Bench 2.1"
    And the entity "dataset:terminal-bench-2-1" has alias "TB-2.1"

  Scenario: The same name cannot be added twice, however it is spelled
    Given the graph has a dataset "SWE-bench Verified"
    When I run graph add --type dataset --name "swe bench verified" --slug other
    Then the command fails
    And the error mentions "already in the graph"
    And the graph has 1 entity

  Scenario: A name that is already another entity's alias is held back
    Given the graph has a method "Retrieval-Augmented Generation"
    And the method "Retrieval-Augmented Generation" also goes by "RAG"
    When I run graph add --type method --name RAG
    Then the command exits with code 3
    And the error mentions "same name as an alias"
    And the error mentions "method:retrieval-augmented-generation"

  Scenario: A version variant is held back until someone decides
    Given the graph has a dataset "Terminal-Bench 2.1"
    When I run graph add --type dataset --name "Terminal-Bench 2.0"
    Then the command exits with code 3
    And the error mentions "possible duplicates"
    And the error mentions "dataset:terminal-bench-2-1"
    And the graph has 1 entity

  Scenario: A variant confirmed as different is added and remembered
    Given the graph has a dataset "Terminal-Bench 2.1"
    When I run graph add --type dataset --name "Terminal-Bench 2.0" --distinct "Terminal-Bench 2.1"
    Then the command succeeds
    And the entity "dataset:terminal-bench-2-0" is marked distinct from "dataset:terminal-bench-2-1"
    When I run graph dupes
    Then the output mentions "no likely duplicates"

  Scenario: An acronym given as an alias finds the existing entity
    Given the graph has a method "RAG"
    When I run graph add --type method --name "Retrieval-Augmented Generation" --alias RAG
    Then the command exits with code 3
    And the error mentions "method:rag"

  Scenario: Different kinds of thing never clash
    Given the graph has a dataset "Mamba"
    When I run graph add --type model --name Mamba
    Then the command succeeds
    And the graph has 2 entities

  Scenario: People with the same name need a stable id to be told apart
    Given the graph holds a author "Wei Zhang" with id "author:wei-zhang"
    When I run graph add --type author --name "Wei Zhang" --id s2=1234
    Then the command fails
    And the error mentions "already in the graph"
    When I run graph add --type author --name "Wei Zhang" --id s2=1234 --distinct author:wei-zhang
    Then the command succeeds
    And the output mentions "added author:wei-zhang-2"
    And the graph has 2 entities

  Scenario: The same external id means the same thing
    Given the graph has a dataset "Terminal Bench"
    When I run graph update "Terminal Bench" --id hf=org/terminal-bench
    And I run graph add --type dataset --name "Terminal tasks" --id hf=org/terminal-bench
    Then the command fails
    And the error mentions "same id (hf)"

  Scenario: Linking a paper to what it uses
    Given the graph holds a paper "Mamba" with id "paper:2312.00752"
    And the graph has a dataset "The Pile"
    When I run graph link paper:2312.00752 evaluates-on "The Pile" --source "ARXIV:2312.00752, section 4" --status verified
    Then the command succeeds
    And the graph has the relation "paper:2312.00752" evaluates-on "dataset:the-pile"
    And the relation "paper:2312.00752" evaluates-on "dataset:the-pile" is verified

  Scenario: Linking twice changes nothing
    Given the graph holds a paper "Mamba" with id "paper:2312.00752"
    And the graph has a dataset "The Pile"
    When I run graph link paper:2312.00752 uses "The Pile" --source s --status inferred
    And I run graph link paper:2312.00752 uses "The Pile" --source s --status inferred
    Then the output mentions "already linked"
    And the graph has 1 relations

  Scenario: A relation needs a source and a status
    Given the graph holds a paper "Mamba" with id "paper:2312.00752"
    And the graph has a dataset "The Pile"
    When I run graph link paper:2312.00752 uses "The Pile"
    Then the command exits with code 2

  Scenario: An ambiguous name must be replaced by an id
    Given the graph holds a author "Wei Zhang" with id "author:wei-zhang"
    And the graph holds a author "Wei Zhang" with id "author:wei-zhang-2"
    And "author:wei-zhang-2" is marked as distinct from "author:wei-zhang"
    And the graph holds a paper "A paper" with id "paper:a"
    When I run graph link paper:a authored-by "Wei Zhang" --source s --status verified
    Then the command fails
    And the error mentions "author:wei-zhang, author:wei-zhang-2"
    And the graph has 0 relations
    When I run graph link paper:a authored-by author:wei-zhang-2 --source s --status verified
    Then the command succeeds

  Scenario: Merging a duplicate keeps every connection
    Given the graph has a method "Retrieval-Augmented Generation"
    And the graph holds a method "RAG pipelines" with id "method:rag-pipelines"
    And the graph holds a paper "A paper" with id "paper:a"
    And "paper:a" uses "method:rag-pipelines" is recorded as inferred
    When I run graph merge method:retrieval-augmented-generation method:rag-pipelines
    Then the command succeeds
    And the graph has no entity "method:rag-pipelines"
    And the entity "method:retrieval-augmented-generation" has alias "RAG pipelines"
    And the graph has the relation "paper:a" uses "method:retrieval-augmented-generation"

  Scenario: Entities checked to be different cannot be merged
    Given the graph holds a method "Alpha" with id "method:alpha"
    And the graph holds a method "Beta" with id "method:beta"
    And "method:alpha" is marked as distinct from "method:beta"
    When I run graph merge method:alpha method:beta
    Then the command fails
    And the error mentions "marked as distinct"

  Scenario: Removing an entity removes its connections
    Given the graph holds a paper "A paper" with id "paper:a"
    And the graph holds a tool "A tool" with id "tool:t"
    And "paper:a" uses "tool:t" is recorded as verified
    When I run graph remove tool:t
    Then the graph has no entity "tool:t"
    And the graph has 0 relations

  Scenario: Papers with nothing extracted yet are listed
    Given the graph holds a paper "Read paper" with id "paper:read"
    And the graph holds a paper "Waiting paper" with id "paper:waiting"
    And the graph has a dataset "Some data"
    And "paper:read" evaluates-on "dataset:some-data" is recorded as verified
    When I run graph islands
    Then the output mentions "paper:waiting"
    And the output does not mention "paper:read"

  Scenario: A paper's citation counts are saved with the date they were checked
    Given the graph holds a paper "Paper A" with id "paper:2611.00001"
    And Semantic Scholar's batch output in "s2.json" gives ARXIV:2611.00001 42 citations
    When I run graph standing s2.json
    Then the command succeeds
    And the paper "paper:2611.00001" has 42 citations checked today
    When I run graph search 2611.00001
    Then the output mentions "42 citations, checked"
    When I run graph standing-due due.txt
    Then the output mentions "no papers due"
    And the file "due.txt" does not contain "2611.00001"

  Scenario: Papers whose citations were never checked are due, if they can be looked up
    Given the graph holds a paper "Paper A" with id "paper:2611.00001"
    And the graph holds a paper "A blog post" with id "paper:blog"
    When I run graph standing-due due.txt
    Then the output mentions "1 paper due"
    And the file "due.txt" contains "ARXIV:2611.00001"
    And the file "due.txt" does not contain "blog"

  Scenario: A batch with reference lists links the papers that cite each other
    Given the graph holds a paper "Newer" with id "paper:2611.00002"
    And the graph holds a paper "Older" with id "paper:2511.00001"
    And Semantic Scholar's batch output in "s2.json" gives ARXIV:2611.00002 3 citations, citing ARXIV:2511.00001
    When I run graph standing s2.json
    Then the command succeeds
    And the output mentions "1 citation link added"
    And the graph has the relation "paper:2611.00002" cites "paper:2511.00001"
    When I run graph standing s2.json
    Then the output mentions "0 citation links added"

  Scenario: A paper Semantic Scholar does not know is not asked about again for a month
    Given the graph holds a paper "New paper" with id "paper:2611.00001"
    And Semantic Scholar's batch output in "s2.json" says it does not know ARXIV:2611.00001
    When I run graph standing s2.json
    Then the output mentions "1 without citation data"
    And the paper "paper:2611.00001" was checked today but has no citation counts
    When I run graph search 2611.00001
    Then the output mentions "no citation data, checked"
    When I run graph standing-due due.txt
    Then the output mentions "no papers due"

  Scenario: Saving many papers' citation counts takes one line of output
    Given the graph holds a paper "Paper A" with id "paper:2611.00001"
    And the graph holds a paper "Paper B" with id "paper:2611.00002"
    And Semantic Scholar's batch output in "s2.json" gives ARXIV:2611.00001 42 citations
    When I run graph standing s2.json
    Then the output mentions "1 paper updated, 0 records matched no paper in the graph"
    And the output does not mention "paper:2611.00001"

  Scenario: Fetching a paper's citation links also saves its citation counts
    Given the graph holds a paper "Paper A" with id "paper:2611.00001"
    And Semantic Scholar's record in "s2.json" gives ARXIV:2611.00001 7 citations and no links
    When I run graph cites paper:2611.00001 s2.json
    Then the command succeeds
    And the output mentions "standing: paper:2611.00001: 7 citations"
    And the paper "paper:2611.00001" has 7 citations checked today

  Scenario: Only papers checked long enough ago are due again
    Given the graph holds a paper "Old check" with id "paper:2611.00001"
    And the graph holds a paper "Recent check" with id "paper:2611.00002"
    And the paper "paper:2611.00001" was checked 40 days ago with 3 citations
    And the paper "paper:2611.00002" was checked 2 days ago with 5 citations
    When I run graph standing-due due.txt
    Then the file "due.txt" contains "ARXIV:2611.00001"
    And the file "due.txt" does not contain "2611.00002"
    When I run graph standing-due due.txt --days 1
    Then the file "due.txt" contains "ARXIV:2611.00002"

  Scenario: Merging two copies of a paper keeps the newer citation counts
    Given the graph holds a paper "Paper A" with id "paper:a"
    And the graph holds a paper "Paper A copy" with id "paper:b"
    And the paper "paper:a" was checked 40 days ago with 3 citations
    And the paper "paper:b" was checked 2 days ago with 9 citations
    When I run graph merge paper:a paper:b
    Then the command succeeds
    And the paper "paper:a" has 9 citations

  Scenario: Made-up citation counts are refused
    Given the graph holds a paper "Paper A" with id "paper:2611.00001"
    And the paper "paper:2611.00001" has a standing with no checked date
    When I run graph validate
    Then the command fails
    And the error mentions "standing has bad or missing checked"

  Scenario: An invalid graph is refused instead of silently repaired
    Given the graph files contain an invalid entity
    When I run graph validate
    Then the command fails
    And the error mentions "url must be text"
    When I run graph add --type tool --name Fine
    Then the command fails
    And the graph has 1 entity

  Scenario: Connections can be traced through the graph
    Given the graph holds a paper "Paper A" with id "paper:a"
    And the graph holds a tool "Tool B" with id "tool:b"
    And the graph holds a dataset "Data C" with id "dataset:c"
    And "paper:a" uses "tool:b" is recorded as verified
    And "tool:b" evaluates-on "dataset:c" is recorded as inferred
    When I run graph path "Paper A" "Data C"
    Then the output mentions "evaluates-on"
    And the output mentions "inferred"

  Scenario: A lock file left by a crashed command blocks nobody
    Given the file "research/graph/.lock" contains the text "left by a command that crashed"
    When I run graph validate
    Then the command succeeds

  Scenario: Several windows can change the graph at the same moment
    When 8 processes each add a different method at the same moment
    Then every process succeeds
    And the graph has 8 more entities than before
    And no temporary files are left behind
