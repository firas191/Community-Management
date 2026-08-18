"""Analyst agent package (brief Section 11.6, Week 7).

An agent that answers questions about an account by calling the project's own
tested analytics functions as read-only tools, then writing an answer grounded in
what those tools returned. Layering:

  tools.py    the read-only tool registry: JSON schemas + dispatch. No LLM here.
  prompts.py  the grounding rules the agent must follow.
  graph.py    the LangGraph think/act loop, with the gateway injected.
  service.py  the DB layer: runs the graph and persists the run + tool trace.

The agent never writes to the database through a tool, and never invents a number:
every figure in an answer comes from a tool result, and the full trace is stored so
any answer can be audited after the fact.
"""
