STATUS=ERROR
sby -f test3.sr_out.sby > /dev/null && STATUS=$(awk '{print $1}' test3.sr_out/status)
echo $STATUS > status
case $STATUS in
    PASS)
        echo "Proved equivalence of partition 'test3.sr_out' using strategy 'pdr'"
    ;;
    FAIL)
        echo "Could not prove equivalence of partition 'test3.sr_out' using strategy 'pdr': partitions not equivalent"
    ;;
    UNKNOWN)
        echo "Could not prove equivalence of partition 'test3.sr_out' using strategy 'pdr': equivalence unknown"
    ;;
    TIMEOUT)
        echo "Could not prove equivalence of partition 'test3.sr_out' using strategy 'pdr': timeout"
    ;;
    *)
        cat test3.sr_out/ERROR 2> /dev/null
        echo "Execution of strategy 'pdr' on partition 'test3.sr_out' encountered an error."
        echo "More details can be found in '/home/ubuntu/FPGA/clean-v11/competition-v11-g41s3isr/test3/candidate/proof/strategies/test3.sr_out/pdr/test3.sr_out/logfile.txt'."
        exit 1
    ;;
esac
exit 0

