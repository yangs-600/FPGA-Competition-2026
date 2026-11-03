yosys -ql run.log run.ys
if grep "SAT temporal induction proof finished - model found for base case: FAIL!" run.log > /dev/null ; then
	echo FAIL > status
	echo "Could not prove equivalence of partition 'test4.only_5b' using strategy 'simple': partitions not equivalent"
elif grep "Reached maximum number of time steps -> proof failed." run.log > /dev/null ; then
	echo UNKNOWN > status
	echo "Could not prove equivalence of partition 'test4.only_5b' using strategy 'simple': equivalence unknown"
elif grep "Interrupted SAT solver: TIMEOUT!" run.log > /dev/null ; then
	echo UNKNOWN > status
	echo "Could not prove equivalence of partition 'test4.only_5b' using strategy 'simple': timeout"
elif grep "Induction step proven: SUCCESS!" run.log > /dev/null ; then
	echo PASS > status
	echo "Proved equivalence of partition 'test4.only_5b' using strategy 'simple'"
else
	echo ERROR > status
	echo "Execution of strategy 'simple' on partition 'test4.only_5b' encountered an error.
Details can be found in '/home/yangsenyu/fpga-windows-native-v25-20261103/proof-shared-runtime-once/formal/test4/baseline/proof/strategies/test4.only_5b/simple/run.log'."
	exit 1
fi
exit 0

