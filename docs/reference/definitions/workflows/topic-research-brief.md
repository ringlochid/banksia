# Topic research brief workflow example

This example mirrors the shipped `topic-research-brief` workflow fixture.

```yaml
kind: workflow
id: topic-research-brief
description: Turn one topic into one concise Markdown research brief with one researcher.
root:
    node_key: root
    kind: root
    role_id: root_planning_lead
    policy_id: standard-root
    description: Delegate one bounded research assignment and close when the Markdown brief is published.
    instruction: >-
      Assign exactly one researcher. Do not add children or broaden the task. Release only after the researcher publishes the research_brief artifact from workspace/research_brief.md.
    criteria:
        - slot: topic_research_brief_criteria
          description: Hard criteria for the first-run research brief.
          criteria:
              - workspace/research_brief.md exists and is published to the research_brief artifact slot
              - brief covers the topic, useful angle, key evidence, tradeoffs, and next step
              - evidence uses two to four surfaced sources, or the brief states source limits
              - confidence and assumptions are visible without reading the transcript
              - no implementation or external publication is performed by this workflow
    children:
        - node_key: research_topic
          kind: worker
          role_id: researcher
          policy_id: standard-worker
          description: Research one topic and publish one concise Markdown brief.
          instruction: >-
            Do a fast bounded source scan for the assigned topic. Use two to four useful sources, compare claims only when they conflict, and write exactly one Markdown file at workspace/research_brief.md. Publish that file as the research_brief artifact and include source limits, assumptions, and confidence in the brief.
          consumes:
              criteria:
                  - slot: topic_research_brief_criteria
          produces:
              artifacts:
                  - slot: research_brief
                    file_hint: research_brief.md
                    description: Concise source-grounded Markdown research brief for the topic.
```
