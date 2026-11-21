Feature: A recap page that shows what has been done so far
  As a reader who works across several sessions
  I want one page with my papers, insights, everything I told Claude, and graph
  So that I can see my progress and what still needs doing

  Scenario: A turn that changed the research files ends only after the recap is refreshed
    Given a workspace just set up by init
    When the turn ends
    Then the turn is allowed to end
    Given the user added the pin "Critic loop"
    When the turn ends
    Then Claude is told to refresh the recap and log the questions
    When the recap page is refreshed
    Then the recap folder holds the page, its script library, and the data
    When the turn ends
    Then the turn is allowed to end
