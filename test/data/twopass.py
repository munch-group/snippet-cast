#: Let's write a tiny counter. / We're about to look at a tiny counter function.
def counter(n):                #: First, the signature. /
    total = 0                  #: Total starts at zero. / Total starts at zero, {total}.
    for i in range(n):         #: /Loop n times, adding i each time.
        total += i             #: /total becomes {total} after adding {i}.
    return total               #: Finally return it. / Return the total, {total}.
result = counter(4)            #: /Call counter with four; result becomes six.
