#: Let's trace an iterative Fibonacci function as it runs.
def fib(n):             #: The first line names the fib-function and defines its parameters - in this case a single one named n. The first line ends with a colon and the code that runs when the function is called is what is indented on the lines below. 
    a, b = 0, 1         #: Start from the first two Fibonacci numbers, zero and one.
    for _ in range(n):  #: Loop n times; the counter itself is unused.
        a, b = b, a + b #: Advance the pair — b becomes the running sum.
    return a            #: After the loop, a holds the nth Fibonacci number.
result = fib(7)         #: Call fib with seven; result becomes thirteen.
