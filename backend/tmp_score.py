from memory.retrieval import stacktrace_score

hist = "Exception in worker at process.foo (redis) at line 123"
new = "Traceback (most recent call last): redis.client.ConnectionError in process.foo at 123"
print(stacktrace_score(new, hist))
