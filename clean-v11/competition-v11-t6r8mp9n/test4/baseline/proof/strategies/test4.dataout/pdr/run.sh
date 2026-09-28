STATUS=ERROR
sby -f test4.dataout.sby > /dev/null && STATUS=$(awk '{print $1}' test4.dataout/status)
echo $STATUS > status
case $STATUS in
    PASS)
        echo "Proved equivalence of partition 'test4.dataout' using strategy 'pdr'"
    ;;
    FAIL)
        echo "Could not prove equivalence of partition 'test4.dataout' using strategy 'pdr': partitions not equivalent"
    ;;
    UNKNOWN)
        echo "Could not prove equivalence of partition 'test4.dataout' using strategy 'pdr': equivalence unknown"
    ;;
    TIMEOUT)
        echo "Could not prove equivalence of partition 'test4.dataout' using strategy 'pdr': timeout"
    ;;
    *)
        cat test4.dataout/ERROR 2> /dev/null
        echo "Execution of strategy 'pdr' on partition 'test4.dataout' encountered an error."
        echo "More details can be found in '/home/ubuntu/FPGA/clean-v11/competition-v11-t6r8mp9n/test4/baseline/proof/strategies/test4.dataout/pdr/test4.dataout/logfile.txt'."
        exit 1
    ;;
esac
exit 0

