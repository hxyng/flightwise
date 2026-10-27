import flightwise.agent as agent

agent.STREAM = False            # unit tests script llm.chat; streaming is exercised end to end
agent.TEMPLATE_ANSWERS = False  # most tests script the model-written answer; test_answers covers templates
