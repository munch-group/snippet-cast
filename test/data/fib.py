#: Let's trace an iterative Fibonacci function as it runs.
def fib(n):             #: We define fib, which takes a single argument n.
    a, b = 0, 1         #: Start from the first two Fibonacci numbers, zero and one.
    for _ in range(n):  #: Loop n times; the counter itself is unused.
        a, b = b, a + b #: Advance the pair — b becomes the running sum.
    return a            #: After the loop, a holds the nth Fibonacci number.
result = fib(7)         #: Call fib with seven; result becomes thirteen.
