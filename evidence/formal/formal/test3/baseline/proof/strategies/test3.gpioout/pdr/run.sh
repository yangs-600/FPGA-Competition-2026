STATUS=ERROR
sby -f test3.gpioout.sby > /dev/null && STATUS=$(awk '{print $1}' test3.gpioout/status)
echo $STATUS > status
case $STATUS in
    PASS)
        echo "Proved equivalence of partition 'test3.gpioout' using strategy 'pdr'"
    ;;
    FAIL)
        echo "Could not prove equivalence of partition 'test3.gpioout' using strategy 'pdr': partitions not equivalent"
    ;;
    UNKNOWN)
        echo "Could not prove equivalence of partition 'test3.gpioout' using strategy 'pdr': equivalence unknown"
    ;;
    TIMEOUT)
        echo "Could not prove equivalence of partition 'test3.gpioout' using strategy 'pdr': timeout"
    ;;
    *)
        cat test3.gpioout/ERROR 2> /dev/null
        echo "Execution of strategy 'pdr' on partition 'test3.gpioout' encountered an error."
        echo "More details can be found in '/home/yangsenyu/fpga-windows-native-v25-20261103/proof-shared-runtime-once/formal/test3/baseline/proof/strategies/test3.gpioout/pdr/test3.gpioout/logfile.txt'."
        exit 1
    ;;
esac
exit 0

