# Footnote narration: code stays short, bodies live at the bottom.
total = 0           #: 1)
for i in range(4):  #: 2)
    total += i      #: 3)
print(total)        #: 4)

#: 1) We start with a running total of zero, which is the value every
# accumulation like this one has to begin from — there is nothing to add
# to yet. / Here the total is still {total}.
#: 2) Then we walk over the numbers zero through three, one at a time,
# binding each of them to i in turn. / The loop variable i is {i}.
#: 3) Each pass adds the current number to the running total, so the
# total grows by a little more on every iteration. / After the loop the
# total has reached {total}.
#: 4) Finally we print the result, which is the sum of zero through
# three. / That prints {total}.
