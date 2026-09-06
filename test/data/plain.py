# No '#:' narration anywhere — render with --pause to get one silent
# frame per code line, then narrate it in a video editor.
def fib(n):
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a

result = fib(7)
